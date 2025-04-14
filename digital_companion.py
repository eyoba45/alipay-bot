"""
Digital Shopping Companion with Ethiopian Female Character
A beautiful Ethiopian shopping assistant with AI-powered personality and Amharic voice capabilities
"""

import os
import logging
import json
import time
import random
from datetime import datetime, timedelta

import anthropic
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import session_scope
from models import User, CompanionProfile, CompanionInteraction
from companion_config import COMPANION_PROFILES, BASE_SYSTEM_PROMPT

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class DigitalCompanion:
    """Digital Shopping Companion with Ethiopian female character and Amharic voice capabilities"""
    
    def __init__(self, bot):
        """Initialize the digital companion"""
        self.bot = bot
        self.logger = logging.getLogger('digital_companion')
        self.anthropic_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self.companion_profiles = COMPANION_PROFILES
        self.avatar_folder = "avatars"
        
        # Create avatars folder if it doesn't exist
        if not os.path.exists(self.avatar_folder):
            os.makedirs(self.avatar_folder)
        
        self.logger.info("Digital Companion initialized with Anthropic API")
    
    def get_user_companion(self, user_id):
        """Get or create companion profile for a user"""
        with session_scope() as session:
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if not user:
                self.logger.warning(f"User {user_id} not found in database")
                return None
                
            profile = session.query(CompanionProfile).filter_by(user_id=user.id).first()
            if not profile:
                # Create default profile
                self.logger.info(f"Creating new companion profile for user {user.telegram_id}")
                profile = CompanionProfile(
                    user_id=user.id,
                    companion_name="Selam",
                    relationship_level=1,
                    preferred_language="amharic",
                    interaction_style="friendly"
                )
                session.add(profile)
                session.commit()
            
            return {
                "user_id": user.id,
                "user_telegram_id": user.telegram_id,
                "user_name": user.name,
                "companion_name": profile.companion_name,
                "relationship_level": profile.relationship_level,
                "preferred_language": profile.preferred_language,
                "interaction_style": profile.interaction_style,
                "config": self.companion_profiles.get(profile.companion_name.lower(), 
                                                   self.companion_profiles["selam"])
            }
    
    def send_greeting(self, chat_id, user_data=None):
        """Send a personalized greeting with companion avatar"""
        if not user_data:
            user_data = self.get_user_companion(chat_id)
            if not user_data:
                self.logger.warning(f"Cannot send greeting to {chat_id} - user not found")
                return False
        
        # Prepare greeting message with companion image
        companion_config = user_data["config"]
        greeting = self._select_greeting(user_data)
        
        # Send companion avatar image
        avatar_path = companion_config["avatar_image"]
        
        if avatar_path and os.path.exists(avatar_path):
            with open(avatar_path, 'rb') as photo:
                self.bot.send_photo(
                    chat_id, 
                    photo, 
                    caption=greeting,
                    reply_markup=self._get_companion_keyboard()
                )
        else:
            # Fallback if image not found
            self.logger.warning(f"Avatar image not found at {avatar_path}, sending text only")
            self.bot.send_message(
                chat_id,
                greeting,
                reply_markup=self._get_companion_keyboard()
            )
        
        # Store this interaction
        self._store_interaction(user_data["user_id"], greeting, "greeting")
        
        return True
    
    def _select_greeting(self, user_data):
        """Select appropriate greeting based on relationship level and time of day"""
        config = user_data["config"]
        relationship_level = user_data["relationship_level"]
        
        # Basic greeting for new users
        if relationship_level <= 2:
            return random.choice(config["greeting_phrases"])
        
        # More personalized greeting for established relationships
        hour = datetime.now().hour
        if 5 <= hour < 12:
            time_greeting = "ጥሩ ጠዋት! (Good morning!)"
        elif 12 <= hour < 18:
            time_greeting = "ጥሩ ከሰዓት በኋላ! (Good afternoon!)"
        else:
            time_greeting = "ጥሩ ምሽት! (Good evening!)"
            
        # Add more personalization for higher relationship levels
        if relationship_level >= 5:
            # Get recent interactions to personalize
            with session_scope() as session:
                recent = session.query(CompanionInteraction)\
                    .filter_by(user_id=user_data["user_id"])\
                    .order_by(CompanionInteraction.created_at.desc())\
                    .first()
                    
                if recent and ("product" in recent.message_text.lower() or "ምርት" in recent.message_text):
                    return f"{time_greeting} {user_data['user_name']}, እንደገና ስመለሰዎ ደስ ብሎኛል። እየፈለጉት ያለውን ምርት አግኝተዋል? ({time_greeting} {user_data['user_name']}, so nice to see you again! Did you find the product you were looking for?)"
        
        # Standard greeting with time of day
        return f"{time_greeting} {user_data['user_name']}, {config['greeting_phrases'][2]}"
    
    def _get_companion_keyboard(self):
        """Create inline keyboard for companion interactions"""
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("🛍️ ግዢ እርዳታ (Shopping Help)", callback_data="companion_shopping"),
            InlineKeyboardButton("❓ ጥያቄዎች (Questions)", callback_data="companion_questions")
        )
        markup.row(
            InlineKeyboardButton("💫 ምክሮች (Recommendations)", callback_data="companion_recommendations"),
            InlineKeyboardButton("💬 መልስ (Just Chat)", callback_data="companion_chat")
        )
        return markup
    
    def process_message(self, message):
        """Process user message and respond in companion's personality"""
        user_id = message.from_user.id
        user_data = self.get_user_companion(user_id)
        if not user_data:
            self.logger.warning(f"Cannot process message for {user_id} - user not found")
            return False
            
        # Show typing indicator for realism
        self.bot.send_chat_action(message.chat.id, 'typing')
        
        # Get user's message
        user_text = message.text
        
        # Generate AI response using Anthropic
        response = self._generate_ai_response(user_text, user_data)
        
        # Store interaction
        self._store_interaction(user_data["user_id"], user_text, "message")
        
        # Send response
        self.bot.send_message(
            message.chat.id,
            response,
            reply_markup=self._get_companion_keyboard()
        )
        
        # Update relationship level periodically
        self._update_relationship_level(user_data["user_id"])
        
        return True
    
    def _generate_ai_response(self, user_text, user_data):
        """Generate AI response using Anthropic Claude"""
        # The newest Anthropic model is "claude-3-5-sonnet-20241022" which was released October 22, 2024
        try:
            # Create system prompt with companion personality
            system_prompt = self._create_system_prompt(user_data)
            
            # Log request
            self.logger.info(f"Sending request to Anthropic for user {user_data['user_telegram_id']}")
            
            # Make API call to Anthropic
            response = self.anthropic_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1024,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_text}
                ]
            )
            
            # Return text response from Claude
            return response.content[0].text
            
        except Exception as e:
            self.logger.error(f"Anthropic API error: {e}")
            return "ይቅርታ, አሁን መልስ ለመስጠት አልቻልኩም። እባክዎ ቆይተው ይሞክሩ። (Sorry, I couldn't respond right now. Please try again later.)"
    
    def _create_system_prompt(self, user_data):
        """Create system prompt for Anthropic based on companion personality and relationship level"""
        config = user_data["config"]
        relationship_level = user_data["relationship_level"]
        
        # Create formatted prompt from template
        prompt = BASE_SYSTEM_PROMPT.format(
            name=config["name"],
            traits=", ".join(config["personality_traits"]),
            level=relationship_level
        )
        
        # Adjust style based on relationship level
        if relationship_level <= 3:
            prompt += "\nBe polite and professional, but somewhat formal as you're still getting to know the user."
        elif relationship_level <= 6:
            prompt += "\nBe friendly and personable, occasionally using light humor as you know the user fairly well."
        else:
            prompt += "\nBe warm and familiar, using friendly language and occasional jokes as you have a strong relationship with this user."
        
        # Adding user context
        prompt += f"\n\nThe user's name is {user_data['user_name']}."
        
        return prompt
    
    def _store_interaction(self, user_id, message_text, interaction_type):
        """Store user interaction for future personalization"""
        with session_scope() as session:
            interaction = CompanionInteraction(
                user_id=user_id,
                message_text=message_text,
                interaction_type=interaction_type,
                created_at=datetime.utcnow()
            )
            session.add(interaction)
            
            # Update last interaction time
            profile = session.query(CompanionProfile).filter_by(user_id=user_id).first()
            if profile:
                profile.last_interaction = datetime.utcnow()
    
    def _update_relationship_level(self, user_id):
        """Update relationship level based on interaction frequency and quality"""
        with session_scope() as session:
            profile = session.query(CompanionProfile).filter_by(user_id=user_id).first()
            if not profile:
                return
                
            # Count interactions in the past week
            week_ago = datetime.utcnow() - timedelta(days=7)
            interaction_count = session.query(CompanionInteraction)\
                .filter(
                    CompanionInteraction.user_id == user_id,
                    CompanionInteraction.created_at >= week_ago
                ).count()
                
            # Increase relationship level based on interaction frequency
            if interaction_count > 20 and profile.relationship_level < 10:
                profile.relationship_level += 1
                self.logger.info(f"Increased relationship level to {profile.relationship_level} for user_id {user_id}")
            elif interaction_count > 10 and profile.relationship_level < 7:
                profile.relationship_level += 1
                self.logger.info(f"Increased relationship level to {profile.relationship_level} for user_id {user_id}")
            elif interaction_count > 5 and profile.relationship_level < 5:
                profile.relationship_level += 1
                self.logger.info(f"Increased relationship level to {profile.relationship_level} for user_id {user_id}")
    
    def handle_callback(self, call):
        """Handle callback queries from companion keyboard"""
        callback_data = call.data
        user_id = call.from_user.id
        user_data = self.get_user_companion(user_id)
        
        if not user_data:
            self.logger.warning(f"Cannot handle callback for {user_id} - user not found")
            self.bot.answer_callback_query(call.id, "Please register first!")
            return False
        
        # Shopping help button
        if callback_data == "companion_shopping":
            self.bot.answer_callback_query(call.id)
            message = "በምን መንገድ ልርዳዎት? ምርት መፈለግ፣ ትዕዛዝ ማስቀመጥ፣ ወይም የእርስዎን ትዕዛዞች መከታተል? (How can I help you with shopping? Find a product, place an order, or track your orders?)"
            self.bot.send_message(
                call.message.chat.id,
                message,
                reply_markup=self._get_shopping_keyboard()
            )
            self._store_interaction(user_data["user_id"], message, "shopping_help")
            
        # Questions button
        elif callback_data == "companion_questions":
            self.bot.answer_callback_query(call.id)
            message = "ስለ ትዕዛዝዎ፣ ስለ ክፍያ ወይም ስለ ተመላሽ ምን ጥያቄ አለዎት? (What questions do you have about orders, payment, or refunds?)"
            self.bot.send_message(
                call.message.chat.id,
                message,
                reply_markup=self._get_questions_keyboard()
            )
            self._store_interaction(user_data["user_id"], message, "questions")
            
        # Recommendations button
        elif callback_data == "companion_recommendations":
            self.bot.answer_callback_query(call.id)
            message = "ዛሬ ምን ዓይነት ምርቶችን ማየት ይፈልጋሉ? የሚመርጡትን ልለይልዎ። (What kind of products would you like to see today? I can find recommendations for you.)"
            self.bot.send_message(
                call.message.chat.id,
                message,
                reply_markup=self._get_recommendations_keyboard()
            )
            self._store_interaction(user_data["user_id"], message, "recommendations")
            
        # Chat button
        elif callback_data == "companion_chat":
            self.bot.answer_callback_query(call.id)
            message = "እሺ፣ ስለ ምን መወያየት ይፈልጋሉ? እዚህ አለሁ፣ ማዳመጥ እወዳለሁ። (Sure, what would you like to chat about? I'm here and happy to listen.)"
            self.bot.send_message(
                call.message.chat.id,
                message
            )
            self._store_interaction(user_data["user_id"], message, "chat")
            
        # Category selection from recommendations
        elif callback_data.startswith("companion_category_"):
            category = callback_data.replace("companion_category_", "")
            self.bot.answer_callback_query(call.id)
            message = f"የ{category} ምርቶችን እመርጥልዎታለሁ። ዛሬ ምን እየፈለጉ ነው? (I'm selecting some {category} products for you. What specifically are you looking for today?)"
            self.bot.send_message(
                call.message.chat.id,
                message
            )
            self._store_interaction(user_data["user_id"], message, "category_selection")
        
        # Back button
        elif callback_data == "companion_back":
            self.bot.answer_callback_query(call.id)
            # Go back to main companion menu
            self.send_greeting(call.message.chat.id, user_data)
            
        # Find products button
        elif callback_data == "companion_find_products":
            self.bot.answer_callback_query(call.id)
            message = "ምን አይነት ምርት እየፈለጉ ነው? ተጨማሪ ዝርዝሮችን ይንገሩኝ። (What kind of product are you looking for? Please tell me more details.)"
            self.bot.send_message(
                call.message.chat.id,
                message
            )
            self._store_interaction(user_data["user_id"], message, "find_products")
            
        # Place order button
        elif callback_data == "companion_place_order":
            self.bot.answer_callback_query(call.id)
            message = "ትዕዛዝ ለማስገባት ዝግጁ ነዎት? የአሊፕይ ኢቲኤች የትዕዛዝ ማስገባት ሂደትን አመቻችቻለሁ። (Ready to place an order? I'll guide you through the AliPay ETH ordering process.)"
            self.bot.send_message(
                call.message.chat.id,
                message,
                reply_markup=self._get_companion_keyboard()
            )
            self._store_interaction(user_data["user_id"], message, "place_order")
            
        # Track order button
        elif callback_data == "companion_track_order":
            self.bot.answer_callback_query(call.id)
            message = "ትዕዛዝዎን መከታተል ይፈልጋሉ? የትዕዛዝ ቁጥርዎን ይሰጡኝ እና አግኝቼ እረዳዎታለሁ። (Would you like to track your order? Please provide your order number and I'll help you find it.)"
            self.bot.send_message(
                call.message.chat.id,
                message,
                reply_markup=self._get_companion_keyboard()
            )
            self._store_interaction(user_data["user_id"], message, "track_order")
            
        # Payment, orders, and delivery time buttons
        elif callback_data in ["companion_about_payment", "companion_about_orders", "companion_delivery_time"]:
            self.bot.answer_callback_query(call.id)
            
            if callback_data == "companion_about_payment":
                message = "ክፍያ ለመፈጸም የተለያዩ አማራጮች አሉ፤ ቴሌብር፣ ሲቢኢ፣ ወይም ቻፓ። ልክ እንደተመዘገቡ የ100 ብር የምዝገባ ክፍያ እና ወርሃዊ 150 ብር ($1) የደንበኝነት ክፍያ ይኖራል። ምን ተጨማሪ ጥያቄ አለዎት? (There are various payment options available: TeleBirr, CBE, or Chapa. You'll need to pay a 100 ETB registration fee once, and a monthly subscription of 150 ETB ($1). What else would you like to know?)"
            elif callback_data == "companion_about_orders":
                message = "በአሊፕይ ኢቲኤች የሚደረግ ትዕዛዝ ሂደት ቀላል ነው። ከአሊኤክስፕረስ የሚፈልጉትን ምርት ይምረጡ፣ ሊንኩን ይላኩ፣ እና ለዚያ ትዕዛዝ ገንዘብ ያስቀምጡ። ትዕዛዝን እና ማድረስን እኛ እንከታተላለን። ሌላ ምን ማወቅ ይፈልጋሉ? (The ordering process with AliPay ETH is simple. Find your product on AliExpress, send us the link, and make a deposit for that order. We'll handle the ordering and delivery tracking. What else would you like to know?)"
            else:  # delivery_time
                message = "የማድረስ ጊዜ በተለያዩ ሁኔታዎች ላይ ይወሰናል። አብዛኛው የጭነት ዓይነት ከ2-4 ሳምንታት ይወስዳል። ፈጣን ማስረከብ ከፈለጉ ይህንን ሊጠይቁ ይችላሉ፣ ግን ተጨማሪ ክፍያ ሊኖረው ይችላል። ምን ተጨማሪ ዝርዝሮችን ማወቅ ይፈልጋሉ? (Delivery time depends on various factors. Most shipping methods take 2-4 weeks. You can request expedited delivery, but it may cost extra. What other details would you like to know?)"
                
            self.bot.send_message(
                call.message.chat.id,
                message,
                reply_markup=self._get_companion_keyboard()
            )
            self._store_interaction(user_data["user_id"], message, callback_data.replace("companion_", ""))
        
        return True
    
    def _get_shopping_keyboard(self):
        """Create shopping help keyboard"""
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("🔍 ምርት ፈልግ (Find Products)", callback_data="companion_find_products"),
            InlineKeyboardButton("📦 ትዕዛዝ አስገባ (Place Order)", callback_data="companion_place_order")
        )
        markup.row(
            InlineKeyboardButton("🔄 ትዕዛዝ ክትትል (Track Order)", callback_data="companion_track_order"),
            InlineKeyboardButton("⬅️ ተመለስ (Back)", callback_data="companion_back")
        )
        return markup
    
    def _get_questions_keyboard(self):
        """Create questions keyboard"""
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("💳 ስለ ክፍያ (About Payment)", callback_data="companion_about_payment"),
            InlineKeyboardButton("🛒 ስለ ትዕዛዝ (About Orders)", callback_data="companion_about_orders")
        )
        markup.row(
            InlineKeyboardButton("⏱️ ስለ ማድረሻ ጊዜ (Delivery Time)", callback_data="companion_delivery_time"),
            InlineKeyboardButton("⬅️ ተመለስ (Back)", callback_data="companion_back")
        )
        return markup
    
    def _get_recommendations_keyboard(self):
        """Create recommendations categories keyboard"""
        markup = InlineKeyboardMarkup()
        
        # Get categories from config
        categories = self.companion_profiles["selam"]["shopping_categories"]
        
        # Create pairs of buttons
        for i in range(0, len(categories), 2):
            row = []
            # Add first button
            cat = categories[i].split(' (')[0]  # Get only the Amharic part
            row.append(InlineKeyboardButton(categories[i], callback_data=f"companion_category_{cat}"))
            
            # Add second button if available
            if i+1 < len(categories):
                cat = categories[i+1].split(' (')[0]  # Get only the Amharic part
                row.append(InlineKeyboardButton(categories[i+1], callback_data=f"companion_category_{cat}"))
            
            markup.row(*row)
        
        # Add back button
        markup.row(InlineKeyboardButton("⬅️ ተመለስ (Back)", callback_data="companion_back"))
        return markup
    
    def send_voice_message(self, chat_id, text, user_data=None):
        """Send Amharic voice message"""
        if not user_data:
            user_data = self.get_user_companion(chat_id)
            if not user_data:
                return False
        
        # Extract Amharic text (before parentheses with English)
        amharic_text = text.split('(')[0].strip() if '(' in text else text
        
        # Show recording action
        self.bot.send_chat_action(chat_id, 'record_audio')
        
        try:
            # Generate voice using Anthropic's text-to-speech
            # The newest Anthropic model is "claude-3-5-sonnet-20241022" which was released October 22, 2024
            self.logger.info(f"Generating TTS with Anthropic for user {chat_id}")
            
            # Create audio file using Anthropic TTS
            speech = self.anthropic_client.synthesize_speech(
                model="claude-3-5-sonnet-20241022",
                input=amharic_text,
                voice="default", # Using default voice for now
            )
            
            # Save to temporary file
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_audio:
                temp_audio.write(speech.content)
                temp_audio_path = temp_audio.name
            
            # Send voice message
            with open(temp_audio_path, 'rb') as audio:
                self.bot.send_voice(chat_id, audio, caption=text)
                
            # Clean up
            import os
            os.remove(temp_audio_path)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Voice generation error: {e}")
            # Fall back to text response
            self.bot.send_message(chat_id, text)
            return False
            
    def generate_morning_briefing(self, user_telegram_id):
        """Generate a personalized morning briefing for a user"""
        user_data = self.get_user_companion(user_telegram_id)
        if not user_data:
            return False
            
        # Show typing indicator
        try:
            self.bot.send_chat_action(user_telegram_id, 'typing')
        except Exception as e:
            self.logger.error(f"Error sending chat action: {e}")
            return False
            
        try:
            # Create system prompt for briefing
            system_prompt = f"""
            You are {user_data['config']['name']}, a beautiful Ethiopian shopping assistant.
            
            Generate a warm, friendly morning briefing for {user_data['user_name']} that includes:
            1. A personalized greeting
            2. A brief update on new AliExpress deals that might interest them
            3. A reminder about any subscription or balance information
            
            Keep it concise (3-4 sentences) and engaging.
            Always provide both Amharic and English translations, with Amharic first.
            """
            
            # Generate briefing with Claude
            response = self.anthropic_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1024,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": "Generate a morning briefing that feels authentic and personalized."}
                ]
            )
            
            briefing_text = response.content[0].text
            
            # Send briefing with companion avatar
            avatar_path = user_data['config']['avatar_image']
            if avatar_path and os.path.exists(avatar_path):
                with open(avatar_path, 'rb') as photo:
                    self.bot.send_photo(
                        user_telegram_id, 
                        photo, 
                        caption=briefing_text,
                        reply_markup=self._get_companion_keyboard()
                    )
            else:
                self.bot.send_message(
                    user_telegram_id,
                    briefing_text,
                    reply_markup=self._get_companion_keyboard()
                )
                
            # Store the interaction
            self._store_interaction(user_data['user_id'], briefing_text, "morning_briefing")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error generating morning briefing: {e}")
            return False
