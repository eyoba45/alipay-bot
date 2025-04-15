"""
AliPay ETH Bot AI Assistant
A helpful AI assistant for the AliPay ETH Telegram bot with complete knowledge of all bot features
"""

import os
import logging
import json
import time
import random
from datetime import datetime, timedelta

from groq_api import GroqClient
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
    """AI Assistant for the AliPay ETH Telegram bot with complete knowledge of all bot features"""
    
    def __init__(self, bot):
        """Initialize the digital companion"""
        self.bot = bot
        self.logger = logging.getLogger('digital_companion')
        self.ai_client = GroqClient(api_key=os.environ.get("GROQ_API_KEY"))
        self.companion_profiles = COMPANION_PROFILES
        self.avatar_folder = "avatars"
        self.model = "llama3-70b-8192"  # Default Llama model on Groq
        
        # Create avatars folder if it doesn't exist
        if not os.path.exists(self.avatar_folder):
            os.makedirs(self.avatar_folder)
        
        self.logger.info("Digital Companion initialized with Groq API using Llama models")
    
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
                    companion_name="AI Assistant",
                    relationship_level=1,
                    preferred_language="english",
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
                                                   self.companion_profiles["ai assistant"])
            }
    
    def send_greeting(self, chat_id, user_data=None):
        """Send a personalized greeting with companion avatar"""
        if not user_data:
            user_data = self.get_user_companion(chat_id)
            if not user_data:
                self.logger.warning(f"Cannot send greeting to {chat_id} - user not found")
                return False
        
        # We'll handle conversation state in the bot.py module directly
        # No need to modify any state here to avoid circular imports
            
        # Prepare greeting message with companion image
        companion_config = user_data["config"]
        greeting = self._select_greeting(user_data)
        
        # Send companion avatar image
        avatar_path = companion_config["avatar_image"]
        
        # Show typing indicator before sending message
        self.bot.send_chat_action(chat_id, 'typing')
        
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
            time_greeting = "Good morning!"
        elif 12 <= hour < 18:
            time_greeting = "Good afternoon!"
        else:
            time_greeting = "Good evening!"
            
        # Add more personalization for higher relationship levels
        if relationship_level >= 5:
            # Get recent interactions to personalize
            with session_scope() as session:
                recent = session.query(CompanionInteraction)\
                    .filter_by(user_id=user_data["user_id"])\
                    .order_by(CompanionInteraction.created_at.desc())\
                    .first()
                    
                if recent and "product" in recent.message_text.lower():
                    return f"{time_greeting} {user_data['user_name']}, so nice to see you again! Did you find the product you were looking for?"
        
        # Standard greeting with time of day
        return f"{time_greeting} {user_data['user_name']}, {config['greeting_phrases'][2]}"
    
    def _get_companion_keyboard(self):
        """Create inline keyboard for companion interactions"""
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("🛍️ Shopping Help", callback_data="companion_shopping"),
            InlineKeyboardButton("❓ Questions", callback_data="companion_questions")
        )
        markup.row(
            InlineKeyboardButton("💫 Recommendations", callback_data="companion_recommendations"),
            InlineKeyboardButton("💬 Just Chat", callback_data="companion_chat")
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
        """Generate AI response using Groq with Llama model"""
        try:
            # Create system prompt with companion personality
            system_prompt = self._create_system_prompt(user_data)
            
            # Log request
            self.logger.info(f"Sending request to Groq API for user {user_data['user_telegram_id']}")
            
            # Make API call to Groq
            response = self.ai_client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_text}
                ]
            )
            
            # Return text response from Llama
            return response.content[0].text
            
        except Exception as e:
            self.logger.error(f"Groq API error: {e}")
            return "Sorry, I couldn't respond right now. Please try again later."
    
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
        
        # We'll handle conversation state in the bot.py module directly
        # No need to modify any state here to avoid circular imports
        
        if not user_data:
            self.logger.warning(f"Cannot handle callback for {user_id} - user not found")
            self.bot.answer_callback_query(call.id, "Please register first!")
            return False
        
        # Shopping help button
        if callback_data == "companion_shopping":
            self.bot.answer_callback_query(call.id)
            message = "How can I help you with the bot features? Find a product, place an order, or track your orders?"
            self.bot.send_message(
                call.message.chat.id,
                message,
                reply_markup=self._get_shopping_keyboard()
            )
            self._store_interaction(user_data["user_id"], message, "shopping_help")
            
        # Questions button
        elif callback_data == "companion_questions":
            self.bot.answer_callback_query(call.id)
            message = "What questions do you have about orders, payment, or refunds?"
            self.bot.send_message(
                call.message.chat.id,
                message,
                reply_markup=self._get_questions_keyboard()
            )
            self._store_interaction(user_data["user_id"], message, "questions")
            
        # Recommendations button
        elif callback_data == "companion_recommendations":
            self.bot.answer_callback_query(call.id)
            message = "What kind of products would you like to see today? I can find recommendations for you."
            self.bot.send_message(
                call.message.chat.id,
                message,
                reply_markup=self._get_recommendations_keyboard()
            )
            self._store_interaction(user_data["user_id"], message, "recommendations")
            
        # Chat button
        elif callback_data == "companion_chat":
            self.bot.answer_callback_query(call.id)
            message = "Sure, what would you like to chat about? I'm here and happy to listen."
            self.bot.send_message(
                call.message.chat.id,
                message
            )
            self._store_interaction(user_data["user_id"], message, "chat")
            
        # Category selection from recommendations
        elif callback_data.startswith("companion_category_"):
            category = callback_data.replace("companion_category_", "")
            self.bot.answer_callback_query(call.id)
            message = f"I'm selecting some {category} products for you. What specifically are you looking for today?"
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
            message = "What kind of product are you looking for? Please tell me more details."
            self.bot.send_message(
                call.message.chat.id,
                message
            )
            self._store_interaction(user_data["user_id"], message, "find_products")
            
        # Place order button
        elif callback_data == "companion_place_order":
            self.bot.answer_callback_query(call.id)
            message = "Ready to place an order? I'll guide you through the AliPay ETH ordering process."
            self.bot.send_message(
                call.message.chat.id,
                message,
                reply_markup=self._get_companion_keyboard()
            )
            self._store_interaction(user_data["user_id"], message, "place_order")
            
        # Track order button
        elif callback_data == "companion_track_order":
            self.bot.answer_callback_query(call.id)
            message = "Would you like to track your order? Please provide your order number and I'll help you find it."
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
                message = "There are various payment options available: TeleBirr, CBE, or Chapa. You'll need to pay a 200 ETB registration fee once, and a monthly subscription of 150 ETB ($1). What else would you like to know?"
            elif callback_data == "companion_about_orders":
                message = "The ordering process with AliPay ETH is simple. Find your product on AliExpress, send us the link, and make a deposit for that order. We'll handle the ordering and delivery tracking. What else would you like to know?"
            else:  # delivery_time
                message = "Delivery time depends on various factors. Most shipping methods take 2-4 weeks. You can request expedited delivery, but it may cost extra. What other details would you like to know?"
                
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
            InlineKeyboardButton("🔍 Find Products", callback_data="companion_find_products"),
            InlineKeyboardButton("📦 Place Order", callback_data="companion_place_order")
        )
        markup.row(
            InlineKeyboardButton("🔄 Track Order", callback_data="companion_track_order"),
            InlineKeyboardButton("⬅️ Back", callback_data="companion_back")
        )
        return markup
    
    def _get_questions_keyboard(self):
        """Create questions keyboard"""
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("💳 About Payment", callback_data="companion_about_payment"),
            InlineKeyboardButton("🛒 About Orders", callback_data="companion_about_orders")
        )
        markup.row(
            InlineKeyboardButton("⏱️ Delivery Time", callback_data="companion_delivery_time"),
            InlineKeyboardButton("⬅️ Back", callback_data="companion_back")
        )
        return markup
    
    def _get_recommendations_keyboard(self):
        """Create recommendations categories keyboard"""
        markup = InlineKeyboardMarkup()
        
        # Categories in English only
        english_categories = [
            "📱 Electronics",
            "👕 Fashion",
            "🏠 Home & Garden",
            "🎮 Gaming",
            "💄 Beauty",
            "🎁 Gifts"
        ]
        
        # Create pairs of buttons
        for i in range(0, len(english_categories), 2):
            row = []
            # Add first button
            cat = english_categories[i].split(' ')[1]  # Get category name without emoji
            row.append(InlineKeyboardButton(english_categories[i], callback_data=f"companion_category_{cat}"))
            
            # Add second button if available
            if i+1 < len(english_categories):
                cat = english_categories[i+1].split(' ')[1]  # Get category name without emoji
                row.append(InlineKeyboardButton(english_categories[i+1], callback_data=f"companion_category_{cat}"))
            
            markup.row(*row)
        
        # Add back button
        markup.row(InlineKeyboardButton("⬅️ Back", callback_data="companion_back"))
        return markup
    
    def send_voice_message(self, chat_id, text, user_data=None):
        """Send voice message"""
        if not user_data:
            user_data = self.get_user_companion(chat_id)
            if not user_data:
                return False
        
        # Extract main text (before any parentheses)
        main_text = text.split('(')[0].strip() if '(' in text else text
        
        # Show recording action
        self.bot.send_chat_action(chat_id, 'record_audio')
        
        try:
            self.logger.info(f"Voice message functionality temporarily disabled, sending text for user {chat_id}")
            # For now, we'll just send the text message since Groq doesn't offer TTS
            # In the future, this could be replaced with another TTS service
            
            # Fall back to text response
            self.bot.send_message(chat_id, text)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Voice message error: {e}")
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
            You are {user_data['config']['name']}, a knowledgeable AI Assistant for the bot.
            
            Generate a warm, friendly morning briefing for {user_data['user_name']} that includes:
            1. A personalized greeting
            2. A brief reminder about the bot's features they might find useful
            3. A reminder about subscription or balance information if applicable
            
            Keep it concise (3-4 sentences) and engaging.
            Use only English for all communications.
            """
            
            # Generate briefing with Groq Llama model
            response = self.ai_client.messages.create(
                model=self.model,
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
