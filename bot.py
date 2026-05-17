from keep_alive import keep_alive
import discord
from discord.ext import commands
from datetime import datetime
import os

# 1. SETUP THE BOT WITH PRIVILEGED INTENTS
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# CORE ROUTING CONFIGURATION
PUBLIC_APPLY_CHANNEL_ID = 1505548554263990333   # Public intake portal channel
APPLICATION_LOG_CHANNEL_ID = 1505374160761655436  # Private staff triage channel
LOGS_CHANNEL_ID = 1505376555432415262            # Permanent action logs channel
STAFF_ROLE_ID = 844656256031260672              # Your server's Staff Role ID
WHITELISTED_ROLE_ID = 1366379062741962792        # Your server's Whitelisted Role ID

# LIVE APPLICATION TRACKER 
pending_applicants = set()

# 2. POP-UP FORM FOR STAFF DENIAL REASON
class DenialReasonModal(discord.ui.Modal, title="❌ Specify Denial Reason"):
    reason_input = discord.ui.TextInput(
        label="Reason for Denial", 
        style=discord.TextStyle.paragraph, 
        placeholder="e.g., Incorrect txAdmin code, fake profile link...", 
        required=True
    )

    def __init__(self, original_message, applicant_id):
        super().__init__()
        self.original_message = original_message
        self.applicant_id = applicant_id

    async def on_submit(self, interaction: discord.Interaction):
        # 1. DEFER IMMEDIATELY to prevent 3-second timeout crashes
        await interaction.response.defer(ephemeral=False)
        
        embed = self.original_message.embeds[0]
        
        # VERIFIED FIELD RE-MAPPING MATRIX TARGETS
        embed.set_field_at(2, name="📊 Status", value="🔴 Denied", inline=True)
        embed.set_field_at(3, name="🔍 Reviewed By", value=interaction.user.mention, inline=True)
        embed.set_field_at(4, name="🕒 Reviewed At", value=datetime.now().strftime('%A, %B %d, %Y %I:%M %p'), inline=True)
        embed.set_field_at(5, name="❌ Denial Reason", value=self.reason_input.value, inline=False)

        view = discord.ui.View.from_message(self.original_message)
        for child in view.children:
            child.disabled = True

        await self.original_message.edit(embed=embed, view=view)
        await interaction.followup.send(f"❌ Application denied by {interaction.user.mention} for: {self.reason_input.value}")
        
        pending_applicants.discard(self.applicant_id)

        try:
            logs_channel = await bot.fetch_channel(LOGS_CHANNEL_ID)
            log_embed = discord.Embed(
                title="📥 Whitelist Application Log: DENIED",
                description=f"👤 **Applicant:** <@{self.applicant_id}>\n🔍 **Staff Reviewer:** {interaction.user.mention}\n❌ **Reason:** {self.reason_input.value}",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            await logs_channel.send(embed=log_embed)
        except Exception as e:
            print(f"Logging Error: {e}")

        guild = interaction.guild
        member = guild.get_member(self.applicant_id)
        if member:
            try:
                await member.send(f"❌ Your whitelist application for Project Rev RP has been denied.\n**Reason:** {self.reason_input.value}")
            except discord.Forbidden:
                pass

# 3. AUTOMATED DM VOUCH BUTTONS 
class DMVouchButton(discord.ui.View):
    def __init__(self, staff_message_id, applicant_id, guild_id):
        super().__init__(timeout=None)
        self.staff_message_id = staff_message_id
        self.applicant_id = applicant_id
        self.guild_id = guild_id

    @discord.ui.button(label="Vouch for Them", style=discord.ButtonStyle.green, emoji="👍")
    async def dm_vouch(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = bot.get_guild(self.guild_id)
        if not guild:
            await interaction.response.send_message("❌ Internal server verification link error.", ephemeral=True)
            return

        member = guild.get_member(interaction.user.id)
        if not member:
            await interaction.response.send_message("❌ You must be a member of the Project Rev RP server to vouch!", ephemeral=True)
            return

        has_whitelist = any(role.id == WHITELISTED_ROLE_ID for role in member.roles)
        if not has_whitelist and not member.guild_permissions.administrator:
            await interaction.response.send_message("❌ Action Blocked! Only whitelisted players can vouch.", ephemeral=True)
            return

        # 1. DEFER IMMEDIATELY to protect background API fetch routines
        await interaction.response.defer(ephemeral=True)

        try:
            staff_channel = await bot.fetch_channel(APPLICATION_LOG_CHANNEL_ID)
            message = await staff_channel.fetch_message(self.staff_message_id)
        except discord.NotFound:
            await interaction.followup.send("❌ This application is no longer active or has been processed.", ephemeral=True)
            return

        embed = message.embeds[0]
        current_vouch_field = embed.fields[8].value
        
        if interaction.user.mention in current_vouch_field:
            await interaction.followup.send("⚠️ You have already vouched for this applicant!", ephemeral=True)
            return
            
        if interaction.user.id == self.applicant_id:
            await interaction.followup.send("❌ You cannot vouch for your own application!", ephemeral=True)
            return

        # FIXED STRING TOKENIZER PARSER ENGINE
        try:
            count_text = embed.fields[8].name
            parts = count_text.split("(")
            current_count = int(parts[1].split(")")[0])
        except Exception:
            current_count = 0

        new_count = current_count + 1
        if current_vouch_field == "None":
            new_vouch_value = interaction.user.mention
        else:
            new_vouch_value = f"{current_vouch_field}, {interaction.user.mention}"
        
        embed.set_field_at(8, name=f"👍 Vouches ({new_count})", value=new_vouch_value, inline=False)
        await message.edit(embed=embed)
        
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.followup.send(f"✅ Success! Your verified vouch for <@{self.applicant_id}> has been logged.", ephemeral=True)

# 4. POP-UP FORM (MODAL) FOR APPLICANTS
class WhitelistModal(discord.ui.Modal, title="📋 FiveM Whitelist Application"):
    name_input = discord.ui.TextInput(label="👤 Name", placeholder="Your character or real name...", required=True)
    age_input = discord.ui.TextInput(label="🎂 Age", placeholder="Your age...", required=True, min_length=2, max_length=2)
    steam_url = discord.ui.TextInput(label="🌐 Steam Profile Link", placeholder="https://steamcommunity.com...", required=True)
    fivem_code = discord.ui.TextInput(label="🔑 txAdmin Request Code", placeholder="E.g., XXXXXX or connection ID...", required=True)
    voucher_tag = discord.ui.TextInput(label="💬 Voucher Discord Username (Optional)", placeholder="Leave blank or type N/A if none...", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id in pending_applicants:
            await interaction.response.send_message("⚠️ You already have an active application pending staff review!", ephemeral=True)
            return

        pending_applicants.add(interaction.user.id)
        await interaction.response.send_message("✅ Your application has been submitted for staff review!", ephemeral=True)
        
        embed = discord.Embed(title="📋 Whitelist Application", color=discord.Color.dark_theme())
        embed.description = f"**Applicant:** {interaction.user.mention}\n**Submitted:** {datetime.now().strftime('%A, %B %d, %Y %I:%M %p')}"
        
        embed.add_field(name="👤 Name", value=self.name_input.value, inline=True)
        embed.add_field(name="🎂 Age", value=self.age_input.value, inline=True)
        embed.add_field(name="📊 Status", value="⏳ Pending Review", inline=True)
        embed.add_field(name="🔍 Reviewed By", value="N/A", inline=True)
        embed.add_field(name="🕒 Reviewed At", value="N/A", inline=True)
        embed.add_field(name="❌ Denial Reason", value="N/A", inline=False)
        embed.add_field(name="🌐 Steam Profile Link", value=self.steam_url.value, inline=False)
        embed.add_field(name="🔑 txAdmin Request Code", value=self.fivem_code.value, inline=False)
        embed.add_field(name="👍 Vouches (0)", value="None", inline=False)
        
        embed.set_footer(text=f"Project Rev RP Whitelist • User ID: {interaction.user.id} • Times in GMT+8")

        try:
            review_channel = await bot.fetch_channel(APPLICATION_LOG_CHANNEL_ID)
            staff_msg = await review_channel.send(embed=embed, view=StaffButtons(interaction.user.id, self.name_input.value))
            
            voucher_input = self.voucher_tag.value.strip()
            if voucher_input and voucher_input.lower() != "n/a":
                target_username = voucher_input.lower()
                found_member = None
                
                for member in interaction.guild.members:
                    if member.name.lower() == target_username:
                        found_member = member
                        break
                
                if found_member and found_member.id != interaction.user.id:
                    try:
                        dm_embed = discord.Embed(
                            title="👍 Project Rev RP Vouch Request",
                            description=f"Hello {found_member.mention}!\n\n**{interaction.user.name}** has just submitted a Whitelist Application to **Project Rev RP**.\n\nClick the button below to vouch for them!",
                            color=discord.Color.blue()
                        )
                        await found_member.send(embed=dm_embed, view=DMVouchButton(staff_msg.id, interaction.user.id, interaction.guild.id))
                    except discord.Forbidden:
                        pass
        except Exception as e:
            print(f"Submission Error: {e}")

# 5. INTERACTIVE BUTTON VIEWS (Staff Actions Only)
class StaffButtons(discord.ui.View):
    def __init__(self, applicant_id, character_name):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.character_name = character_name

    def is_staff(self, member: discord.Member) -> bool:
        return any(role.id == STAFF_ROLE_ID for role in member.roles) or member.guild_permissions.administrator

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, emoji="✅")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_staff(interaction.user):
            await interaction.response.send_message("❌ Only server Staff members can approve applications!", ephemeral=True)
            return

        # 1. DEFER IMMEDIATELY to unlock long API logging delays
        await interaction.response.defer(ephemeral=False)

        guild = interaction.guild
        member = guild.get_member(self.applicant_id)
        role = guild.get_role(WHITELISTED_ROLE_ID)

        if member and role:
            try:
                await member.add_roles(role)
                approval_msg = (
                    f"🎉 **Congratulations!** Your whitelist application for **Project Rev RP** has been approved.\n\n"
                    f"⚠️ **CRITICAL STEP BEFORE JOINING:**\n"
                    f"You submitted your whitelist application under the character name: **{self.character_name}**.\n"
                    f"You **MUST** open your FiveM settings and change your FiveM player profile name to exactly match **\"{self.character_name}\"** before connecting to the game server."
                )
                await member.send(approval_msg)
            except discord.Forbidden:
                await interaction.channel.send("⚠️ Warning: I couldn't assign the role. Please drag my bot role HIGHER in your server role settings!")
            except Exception:
                pass

        embed = interaction.message.embeds[0]
        embed.set_field_at(2, name="📊 Status", value="🟢 Approved", inline=True)
        embed.set_field_at(3, name="🔍 Reviewed By", value=interaction.user.mention, inline=True)
        embed.set_field_at(4, name="🕒 Reviewed At", value=datetime.now().strftime('%A, %B %d, %Y %I:%M %p'), inline=True)
        
        for child in self.children:
            child.disabled = True
            
        await interaction.message.edit(embed=embed, view=self)
        await interaction.followup.send(f"✅ Application approved by {interaction.user.mention}")
        pending_applicants.discard(self.applicant_id)

        try:
            logs_channel = await bot.fetch_channel(LOGS_CHANNEL_ID)
            log_embed = discord.Embed(
                title="📥 Whitelist Application Log: APPROVED",
                description=f"👤 **Applicant:** <@{self.applicant_id}>\n🔍 **Staff Reviewer:** {interaction.user.mention}",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            await logs_channel.send(embed=log_embed)
        except Exception as e:
            print(f"Logging Error: {e}")

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, emoji="❌")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_staff(interaction.user):
            await interaction.response.send_message("❌ Only server Staff members can deny applications!", ephemeral=True)
            return

        await interaction.response.send_modal(DenialReasonModal(interaction.message, self.applicant_id))

    @discord.ui.button(label="Vouch", style=discord.ButtonStyle.secondary, emoji="👍")
    async def vouch(self, interaction: discord.Interaction, button: discord.ui.Button):
        has_whitelist = any(role.id == WHITELISTED_ROLE_ID for role in interaction.user.roles)
        if not has_whitelist and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Action Blocked! Only whitelisted players can vouch.", ephemeral=True)
            return

        # 1. DEFER IMMEDIATELY to prevent manual click tracking timeout errors
        await interaction.response.defer(ephemeral=False)

        embed = interaction.message.embeds[0]
        current_vouch_field = embed.fields[8].value
        
        if interaction.user.mention in current_vouch_field:
            await interaction.followup.send("⚠️ You have already vouched for this application!")
            return
        
        if interaction.user.id == self.applicant_id:
            await interaction.followup.send("❌ You cannot vouch for your own application!")
            return
        
        # FIXED STRING PARSER TOKENIZER ENGINE
        try:
            count_text = embed.fields[8].name
            parts = count_text.split("(")
            current_count = int(parts[1].split(")")[0])
        except Exception:
            current_count = 0

        new_count = current_count + 1
        if current_vouch_field == "None":
            new_vouch_value = interaction.user.mention
        else:
            new_vouch_value = f"{current_vouch_field}, {interaction.user.mention}"
        
        embed.set_field_at(8, name=f"👍 Vouches ({new_count})", value=new_vouch_value, inline=False)
        await interaction.message.edit(embed=embed)
        await interaction.followup.send(f"👍 {interaction.user.mention} vouched for this applicant.")

# 6. PUBLIC ENTRY CHANNEL INTERFACE (Click to Start)
class SetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Click to Start Applying", style=discord.ButtonStyle.success, emoji="📥")
    async def apply_now(self, interaction: discord.Interaction, button: discord.ui.Button):
        # NEW CONDITION BLOCK: Scans for existing whitelisted status properties
        has_role = any(role.id == WHITELISTED_ROLE_ID for role in interaction.user.roles)
        if has_role:
            await interaction.response.send_message("❌ Access Blocked! You are already completely whitelisted on Project Rev RP. You do not need to apply again.", ephemeral=True)
            return

        if interaction.user.id in pending_applicants:
            await interaction.response.send_message("❌ You cannot submit multiple applications! You already have a form pending staff review.", ephemeral=True)
            return
            
        await interaction.response.send_modal(WhitelistModal())

# 7. EXPLICIT UTILITY COMMAND ENGINE 
@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🧹 Cleaned up {amount} messages cleanly.", delete_after=3)

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_whitelist(ctx):
    if ctx.channel.id != PUBLIC_APPLY_CHANNEL_ID:
        await ctx.send(f"⚠️ This command must be run inside the designated registration channel (<#{PUBLIC_APPLY_CHANNEL_ID}>)!")
        return

    embed = discord.Embed(
        title="📥 Project Rev RP Whitelist Application Portal", 
        description=(
            "Welcome to the official **Project Rev RP Whitelist Process**. "
            "Please read the server guidelines below before submitting an application.\n\n"
            "**📋 SERVER REQUIREMENTS:**\n"
            "🔹 You must possess a legal copy of Grand Theft Auto V.\n"
            "🔹 You must have a functional headset / microphone setup.\n"
            "🔹 Detailed character backgrounds provide higher approval rates.\n\n\n"
            "⚠️ **IMPORTANT NAME RULE:**\n"
            "The name you fill out in the **👤 Name** field on this application form "
            "**must match your FiveM client profile name exactly** when connecting to our "
            "game server later! If they do not match, you will be automatically disconnected."
        ), 
        color=discord.Color.from_rgb(46, 204, 113)
    )
    embed.set_footer(text="Click the green button below to open up your registration pop-up.")
    await ctx.send(embed=embed, view=SetupView())

@bot.event
async def on_ready():
    print(f"Logged in successfully as: {bot.user.name}")
    print("---------------------------------")

# 8. SECURE TOKEN LOADER
keep_alive()
bot.run(os.getenv('DISCORD_TOKEN'))
