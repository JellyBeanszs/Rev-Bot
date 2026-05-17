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
PUBLIC_APPLY_CHANNEL_ID = 1489533454969208883   # Public intake portal channel
APPLICATION_LOG_CHANNEL_ID = 1505374160761655436  # Private staff triage channel
LOGS_CHANNEL_ID = 1505376555432415262            # Permanent action logs channel
STAFF_ROLE_ID = 844656256031260672              # Your server's Staff Role ID
WHITELISTED_ROLE_ID = 1366379062741962792        # Your server's Whitelisted Role ID

# LIVE APPLICATION TRACKER 
pending_applicants = set()

# GLUE DICTIONARY: Maps individual message tracker arrays to follow automated direct DM responses
active_applications = {}

# 2. POP-UP FORM FOR STAFF DENIAL REASON
class DenialReasonModal(discord.ui.Modal, title="❌ Specify Denial Reason"):
    reason_input = discord.ui.TextInput(
        label="Reason for Denial", 
        style=discord.TextStyle.paragraph, 
        placeholder="e.g., Fake profile link, age requirement mismatch...", 
        required=True
    )

    def __init__(self, original_message, applicant_id):
        super().__init__()
        self.original_message = original_message
        self.applicant_id = applicant_id

    async def on_submit(self, interaction: discord.Interaction):
        # FIXED: Extracting index position from embeds array list securely
        embed = self.original_message.embeds[0]
        
        embed.set_field_at(2, name="📊 Status", value="🔴 Denied", inline=True)
        embed.set_field_at(3, name="🔍 Reviewed By", value=interaction.user.mention, inline=True)
        embed.set_field_at(4, name="🕒 Reviewed At", value=datetime.now().strftime('%A, %B %d, %Y %I:%M %p'), inline=True)
        embed.set_field_at(5, name="❌ Denial Reason", value=self.reason_input.value, inline=False)

        view = discord.ui.View.from_message(self.original_message)
        for child in view.children:
            child.disabled = True

        await self.original_message.edit(embed=embed, view=view)
        await interaction.response.send_message(f"❌ Application denied by {interaction.user.mention} for: {self.reason_input.value}", ephemeral=False)
        
        pending_applicants.discard(self.applicant_id)
        # FIXED: Prevent KeyError crash if app had no voucher mapping tracking context
        active_applications.pop(self.original_message.id, None)

        logs_channel = bot.get_channel(LOGS_CHANNEL_ID)
        if logs_channel:
            log_embed = discord.Embed(
                title="📥 Whitelist Application Log: DENIED",
                description=f"👤 **Applicant:** <@{self.applicant_id}>\n🔍 **Staff Reviewer:** {interaction.user.mention}\n❌ **Reason:** {self.reason_input.value}",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            await logs_channel.send(embed=log_embed)

        guild = interaction.guild
        member = guild.get_member(self.applicant_id)
        if member:
            try:
                await member.send(f"❌ Your whitelist application for Project Rev RP has been denied.\n**Reason:** {self.reason_input.value}")
            except discord.Forbidden:
                pass

# 3. AUTOMATED DM VOUCH BUTTONS 
class DMVouchButton(discord.ui.View):
    def __init__(self, staff_message_id, applicant_id):
        super().__init__(timeout=None)
        self.staff_message_id = staff_message_id
        self.applicant_id = applicant_id

    @discord.ui.button(label="Vouch for Them", style=discord.ButtonStyle.green, emoji="👍")
    async def dm_vouch(self, interaction: discord.Interaction, button: discord.ui.Button):
        staff_channel = bot.get_channel(APPLICATION_LOG_CHANNEL_ID)
        if not staff_channel:
            await interaction.response.send_message("❌ Internal configuration link error.", ephemeral=True)
            return

        try:
            message = await staff_channel.fetch_message(self.staff_message_id)
        except discord.NotFound:
            await interaction.response.send_message("❌ This application is no longer active or has been processed.", ephemeral=True)
            return

        app_data = active_applications.get(self.staff_message_id)
        if not app_data:
            await interaction.response.send_message("❌ This application has already been resolved by staff.", ephemeral=True)
            return

        if interaction.user.id in app_data["vouchers"]:
            await interaction.response.send_message("⚠️ You have already vouched for this applicant!", ephemeral=True)
            return

        app_data["vouch_count"] += 1
        app_data["vouchers"].append(interaction.user.id)
        
        # FIXED: Extraction target list safety check mapping
        embed = message.embeds[0]
        vouch_mentions = ", ".join([f"<@{uid}>" for uid in app_data["vouchers"]])
        
        embed.set_field_at(7, name=f"👍 Vouches ({app_data['vouch_count']})", value=vouch_mentions, inline=False)
        await message.edit(embed=embed)
        
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        
        await interaction.response.send_message(f"✅ Success! Your verified vouch for <@{self.applicant_id}> has been posted to Project Rev RP staff review panels.", ephemeral=True)

# 4. POP-UP FORM (MODAL) FOR APPLICANTS 
class WhitelistModal(discord.ui.Modal, title="📋 FiveM Whitelist Application"):
    name_input = discord.ui.TextInput(label="👤 Name", placeholder="Your character or real name...", required=True)
    age_input = discord.ui.TextInput(label="🎂 Age", placeholder="Your age...", required=True, min_length=2, max_length=2)
    steam_url = discord.ui.TextInput(label="🌐 Steam Profile Link", placeholder="https://steamcommunity.com...", required=True)
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
        embed.add_field(name="👍 Vouches (0)", value="None", inline=False)
        
        embed.set_footer(text=f"Project Rev RP Whitelist • User ID: {interaction.user.id} • Times in GMT+8")

        review_channel = bot.get_channel(APPLICATION_LOG_CHANNEL_ID)
        if review_channel:
            staff_msg = await review_channel.send(embed=embed, view=StaffButtons(interaction.user.id, self.name_input.value))
            
            active_applications[staff_msg.id] = {
                "vouch_count": 0,
                "vouchers": []
            }

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
                            description=f"Hello {found_member.mention}!\n\n**{interaction.user.name}** has just submitted a Whitelist Application to **Project Rev RP** and listed you as their reference voucher.\n\nIf you support their registration entry, click the button below to log your vouch automatically!",
                            color=discord.Color.blue()
                        )
                        await found_member.send(embed=dm_embed, view=DMVouchButton(staff_msg.id, interaction.user.id))
                    except discord.Forbidden:
                        pass

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
                    f"You **MUST** open your FiveM settings and change your FiveM player profile name to exactly match **\"{self.character_name}\"** before connecting to the game server. Failure to do so will result in an automatic kick by our server script!"
                )
                await member.send(approval_msg)
            except discord.Forbidden:
                await interaction.channel.send("⚠️ Warning: I couldn't assign the role. Please ensure my bot role is dragged ABOVE the Whitelisted role in your Server Settings!")
            except Exception:
                pass

        # FIXED: Added array slice index extraction point mapping
        embed = interaction.message.embeds[0]
        embed.set_field_at(2, name="📊 Status", value="🟢 Approved", inline=True)
        embed.set_field_at(3, name="🔍 Reviewed By", value=interaction.user.mention, inline=True)
        embed.set_field_at(4, name="🕒 Reviewed At", value=datetime.now().strftime('%A, %B %d, %Y %I:%M %p'), inline=True)
        
        for child in self.children:
            child.disabled = True
            
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(f"✅ Application approved by {interaction.user.mention}", ephemeral=False)

        pending_applicants.discard(self.applicant_id)
        active_applications.pop(interaction.message.id, None)

        logs_channel = bot.get_channel(LOGS_CHANNEL_ID)
        if logs_channel:
            log_embed = discord.Embed(
                title="📥 Whitelist Application Log: APPROVED",
                description=f"👤 **Applicant:** <@{self.applicant_id}>\n🔍 **Staff Reviewer:** {interaction.user.mention}",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            await logs_channel.send(embed=log_embed)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, emoji="❌")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_staff(interaction.user):
            await interaction.response.send_message("❌ Only server Staff members can deny applications!", ephemeral=True)
            return

        await interaction.response.send_modal(DenialReasonModal(interaction.message, self.applicant_id))

    @discord.ui.button(label="Vouch", style=discord.ButtonStyle.secondary, emoji="👍")
    async def vouch(self, interaction: discord.Interaction, button: discord.ui.Button):
        app_data = active_applications.get(interaction.message.id)
        if not app_data:
            await interaction.response.send_message("❌ This application has already been resolved.", ephemeral=True)
            return

        if interaction.user.id in app_data["vouchers"]:
            await interaction.response.send_message("⚠️ You have already vouched for this application!", ephemeral=True)
            return
        
        if interaction.user.id == self.applicant_id:
            await interaction.response.send_message("❌ You cannot vouch for your own application!", ephemeral=True)
            return
        
        app_data["vouch_count"] += 1
        app_data["vouchers"].append(interaction.user.id)
        
        # FIXED: Extraction target list safety check mapping
        embed = interaction.message.embeds[0]
        vouch_mentions = ", ".join([f"<@{uid}>" for uid in app_data["vouchers"]])
        
        # TARGET SYSTEM CORRECTION INDEX 7
        embed.set_field_at(7, name=f"👍 Vouches ({app_data['vouch_count']})", value=vouch_mentions, inline=False)
        await interaction.message.edit(embed=embed)
        await interaction.response.send_message(f"👍 {interaction.user.mention} vouched for this applicant.", ephemeral=False)

# 6. PUBLIC ENTRY CHANNEL INTERFACE (Click to Start)
class SetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Click to Start Applying", style=discord.ButtonStyle.success, emoji="📥")
    async def apply_now(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in pending_applicants:
            await interaction.response.send_message("❌ You cannot submit multiple applications! You already have a form pending staff review.", ephemeral=True)
            return
            
        await interaction.response.send_modal(WhitelistModal())

# 7. INITIAL SETUP COMMAND
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
