"""
Digital Shopping Companion with Ethiopian female personality
Enhanced shopping experience with Amharic voice and contextual memory
"""

import os
import json
import logging
import time
import random
from datetime import datetime, timedelta
import anthropic
from anthropic import Anthropic
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from models import CompanionInteraction, CompanionProfile, User
from database import session_scope, with_retry
from companion_config import COMPANION_PROFILES, BASE_SYSTEM_PROMPT

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('digital_companion')

class DigitalCompanion:
    """Digital Shopping Companion with Ethiopian female personality"""
    
    def __init__(self, bot):
        """Initialize the digital companion"""
        self.bot = bot
        self.anthropic_client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self.companion_profiles = COMPANION_PROFILES
        logger.info("Digital Companion initialized with beautiful Ethiopian female personality")
        
    @with_retry
    def get_user_companion(self, user_id):
        """Get or create companion profile for a user"""
        with session_scope() as session:
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if not user:
                logger.warning(f"User {user_id} not found in database")
                return None
                
            profile = session.query(CompanionProfile).filter_by(user_id=user.id).first()
            if not profile:
                # Create default profile
                logger.info(f"Creating new companion profile for user {user_id}")
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
                logger.warning(f"Cannot send greeting - user {chat_id} not found")
                return False
        
        # Prepare greeting message with companion image
        companion_config = user_data["config"]
        greeting = self._select_greeting(user_data)
        
        # Send companion avatar image
        try:
            with open(companion_config["avatar_image"], 'rb') as photo:
                self.bot.send_photo(
                    chat_id, 
                    photo, 
                    caption=greeting,
                    reply_markup=self._get_companion_keyboard()
                )
                
                # Store greeting interaction
                self._store_interaction(user_data["user_id"], greeting, "greeting")
                logger.info(f"Greeting sent to user {chat_id}")
                
                return True
        except Exception as e:
            logger.error(f"Failed to send greeting: {e}")
            # Try sending text-only greeting if image fails
            self.bot.send_message(
                chat_id,
                greeting,
                reply_markup=self._get_companion_keyboard()
            )
            return True
    
    def _select_greeting(self, user_data):
        """Select appropriate greeting based on relationship level and time of day"""
        config = user_data["config"]
        relationship_level = user_data["relationship_level"]
        user_name = user_data.get("user_name", "")
        
        # Basic greeting for new users
        if relationship_level <= 2:
            greeting = config["greeting_phrases"][0]
        else:
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
                if user_name:
                    greeting = f"{time_greeting} {user_name}፣ እንዴት ነህ? (How are you?)"
                else:
                    greeting = f"{time_greeting} {config['greeting_phrases'][2]}"
                
                # Get recent interactions to personalize even more
                with session_scope() as session:
                    recent = session.query(CompanionInteraction)\
                        .filter_by(user_id=user_data["user_id"])\
                        .order_by(CompanionInteraction.created_at.desc())\
                        .first()
                        
                    if recent and "product" in recent.message_text.lower():
                        greeting = f"{time_greeting} {user_name if user_name else ''}። እንደገና ስመለሰዎ ደስ ብሎኛል። እየፈለጉት ያለውን ምርት አግኝተዋል? (So nice to see you again! Did you find the product you were looking for?)"
            else:
                greeting = f"{time_greeting} {config['greeting_phrases'][1 if relationship_level >= 3 else 0]}"
        
        return greeting
    
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
            logger.warning(f"User {user_id} not found in database")
            return False
            
        # Show typing indicator for realism
        self.bot.send_chat_action(message.chat.id, 'typing')
        
        # Add small delay for realism
        time.sleep(1)
        
        # Get user's message
        user_text = message.text
        
        # Generate AI response using Anthropic
        response = self._generate_ai_response(user_text, user_data)
        
        # Store interaction
        self._store_interaction(user_data["user_id"], user_text, "user_message")
        self._store_interaction(user_data["user_id"], response, "assistant_message")
        
        # Send response
        self.bot.send_message(
            message.chat.id,
            response,
            reply_markup=self._get_companion_keyboard()
        )
        
        # Update relationship level periodically
        self._update_relationship_level(user_data["user_id"])
        
        # Occasionally send voice messages for more engagement (20% chance)
        if random.random() < 0.2:
            self.send_voice_message(message.chat.id, response, user_data)
        
        return True
    
    def _generate_ai_response(self, user_text, user_data):
        """Generate AI response using Anthropic Claude"""
        # The newest Anthropic model is "claude-3-5-sonnet-20241022" which was released October 22, 2024
        try:
            # Create system prompt with companion personality
            system_prompt = self._create_system_prompt(user_data)
            
            # Get recent conversation history for context
            conversation_history = self._get_conversation_history(user_data["user_id"], limit=5)
            
            messages = []
            # Add conversation history if available
            for msg in conversation_history:
                role = "user" if msg["type"] == "user_message" else "assistant"
                messages.append({"role": role, "content": msg["text"]})
                
            # Add current message if not already in history
            messages.append({"role": "user", "content": user_text})
            
            # If no history or just the current message, add a single message
            if not messages or (len(messages) == 1 and messages[0]["content"] == user_text):
                messages = [{"role": "user", "content": user_text}]
            
            response = self.anthropic_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1024,
                system=system_prompt,
                messages=messages
            )
            
            return response.content[0].text
            
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            return "ይቅርታ, አሁን መልስ ለመስጠት አልቻልኩም። እባክዎ ቆይተው ይሞክሩ። (Sorry, I couldn't respond right now. Please try again later.)"
    
    def _create_system_prompt(self, user_data):
        """Create system prompt for Anthropic based on companion personality and relationship level"""
        config = user_data["config"]
        relationship_level = user_data["relationship_level"]
        
        # Get personality traits as string
        traits = ', '.join(config['personality_traits'])
        
        # Base system prompt
        prompt = BASE_SYSTEM_PROMPT.format(
            name=config['name'],
            traits=traits,
            level=relationship_level
        )
        
        # Adjust style based on relationship level
        if relationship_level <= 3:
            prompt += "\nBe polite and professional, but somewhat formal as you're still getting to know the user."
        elif relationship_level <= 6:
            prompt += "\nBe friendly and personable, occasionally using light humor as you know the user fairly well."
        else:
            prompt += "\nBe warm and familiar, using friendly language and occasional jokes as you have a strong relationship with this user."
        
        # Add shopping context
        prompt += """
Important shopping terms in Amharic:
- ግዢ (gizhi) = shopping/purchase
- ዋጋ (waga) = price
- ትዕዛዝ (tiizaz) = order
- ክፍያ (kifiya) = payment
- ማስረከብ (masrekeb) = delivery

Never forget to use both Amharic and English in every response.
"""
        
        return prompt
    
    def _get_conversation_history(self, user_id, limit=5):
        """Get recent conversation history for context"""
        with session_scope() as session:
            history = session.query(CompanionInteraction)\
                .filter(
                    CompanionInteraction.user_id == user_id,
                    CompanionInteraction.interaction_type.in_(["user_message", "assistant_message"])
                )\
                .order_by(CompanionInteraction.created_at.desc())\
                .limit(limit * 2)\
                .all()
            
            # Convert to list for easier handling and reverse to get chronological order
            result = []
            for item in reversed(history):
                result.append({
                    "type": item.interaction_type,
                    "text": item.message_text,
                    "timestamp": item.created_at.isoformat()
                })
            
            return result
    
    @with_retry
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
            session.commit()
    
    @with_retry
    def _update_relationship_level(self, user_id):
        """Update relationship level based on interaction frequency and quality"""
        with session_scope() as session:
            profile = session.query(CompanionProfile).filter_by(user_id=user_id).first()
            if not profile:
                return
            
            # Set last interaction time
            profile.last_interaction = datetime.utcnow()
                
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
                logger.info(f"User {user_id} relationship level increased to {profile.relationship_level}")
            elif interaction_count > 10 and profile.relationship_level < 7:
                profile.relationship_level += 1
                logger.info(f"User {user_id} relationship level increased to {profile.relationship_level}")
            elif interaction_count > 5 and profile.relationship_level < 5:
                profile.relationship_level += 1
                logger.info(f"User {user_id} relationship level increased to {profile.relationship_level}")
            
            session.commit()
    
    def handle_callback(self, call):
        """Handle callback queries from companion keyboard"""
        callback_data = call.data
        user_id = call.from_user.id
        user_data = self.get_user_companion(user_id)
        
        if not user_data:
            logger.warning(f"User {user_id} not found in database")
            return False
        
        # Show typing indicator for realism
        self.bot.send_chat_action(call.message.chat.id, 'typing')
        
        # Small delay for realism
        time.sleep(0.5)
        
        if callback_data == "companion_shopping":
            self.bot.answer_callback_query(call.id)
            response = "በምን መንገድ ልርዳዎት? ምርት መፈለግ፣ ትዕዛዝ ማስቀመጥ፣ ወይም የእርስዎን ትዕዛዞች መከታተል? (How can I help you? Find a product, place an order, or track your orders?)"
            self.bot.send_message(call.message.chat.id, response)
            self._store_interaction(user_data["user_id"], response, "assistant_message")
            
        elif callback_data == "companion_questions":
            self.bot.answer_callback_query(call.id)
            response = "ስለ ትዕዛዝዎ፣ ስለ ክፍያ ወይም ስለ ተመላሽ ምን ጥያቄ አለዎት? (What questions do you have about orders, payment, or refunds?)"
            self.bot.send_message(call.message.chat.id, response)
            self._store_interaction(user_data["user_id"], response, "assistant_message")
            
        elif callback_data == "companion_recommendations":
            self.bot.answer_callback_query(call.id)
            
            # Get one random shopping category from config
            categories = user_data["config"]["shopping_categories"]
            category = random.choice(categories)
            
            response = f"ዛሬ ምን ዓይነት ምርቶችን ማየት ይፈልጋሉ? {category} በጣም ተወዳጅ ነው። (What kind of products would you like to see today? {category} is very popular.)"
            self.bot.send_message(call.message.chat.id, response)
            self._store_interaction(user_data["user_id"], response, "assistant_message")
            
        elif callback_data == "companion_chat":
            self.bot.answer_callback_query(call.id)
            response = "እሺ፣ ስለ ምን መወያየት ይፈልጋሉ? እዚህ አለሁ፣ ማዳመጥ እወዳለሁ። (Sure, what would you like to chat about? I'm here and happy to listen.)"
            self.bot.send_message(call.message.chat.id, response)
            self._store_interaction(user_data["user_id"], response, "assistant_message")
            
        return True
    
    def send_voice_message(self, chat_id, text, user_data=None):
        """Send Amharic voice message (text to speech using Anthropic)"""
        if not user_data:
            user_data = self.get_user_companion(chat_id)
            if not user_data:
                logger.warning(f"Cannot send voice message - user {chat_id} not found")
                return False
        
        # Extract Amharic text (before parentheses with English)
        # If there are multiple lines, take only the first one for voice
        amharic_text = text.split('(')[0].strip().split('\n')[0]
        
        # Don't process empty or very short texts
        if not amharic_text or len(amharic_text) < 5:
            return False
        
        # Show recording action
        self.bot.send_chat_action(chat_id, 'record_audio')
        
        try:
            # Generate voice using Anthropic's text-to-speech
            # Note: this feature is simulated in current implementation
            # The newest Anthropic model is "claude-3-5-sonnet-20241022" which was released October 22, 2024
            
            # For now, just send a message indicating voice would be sent
            # This is a placeholder until actual voice functionality is implemented
            logger.info(f"Voice message would be sent for: {amharic_text}")
            return True
            
        except Exception as e:
            logger.error(f"Voice generation error: {e}")
            return False
    
    def send_morning_briefing(self):
        """Send morning briefings to users who opted in"""
        logger.info("Preparing morning briefings")
        with session_scope() as session:
            # Find users who opted into morning briefings
            profiles = session.query(CompanionProfile)\
                .filter(CompanionProfile.morning_brief == True)\
                .all()
            
            for profile in profiles:
                try:
                    # Get user telegram_id
                    user = session.query(User).filter_by(id=profile.user_id).first()
                    if not user:
                        continue
                    
                    # Get user's companion data
                    user_data = self.get_user_companion(user.telegram_id)
                    if not user_data:
                        continue
                    
                    # Generate morning briefing
                    briefing = self._generate_morning_briefing(user_data)
                    
                    # Send briefing with companion image
                    config = user_data["config"]
                    with open(config["avatar_image"], 'rb') as photo:
                        self.bot.send_photo(
                            user.telegram_id, 
                            photo, 
                            caption=briefing,
                            reply_markup=self._get_companion_keyboard()
                        )
                    
                    # Store interaction
                    self._store_interaction(user_data["user_id"], briefing, "morning_brief")
                    logger.info(f"Morning briefing sent to user {user.telegram_id}")
                    
                except Exception as e:
                    logger.error(f"Error sending morning briefing: {e}")
    
    def _generate_morning_briefing(self, user_data):
        """Generate personalized morning briefing"""
        # Basic briefing for now, would be enhanced with more personalization
        name = user_data.get("user_name", "")
        name_greeting = f" {name}" if name else ""
        
        briefing = f"ጥሩ ጠዋት{name_greeting}! (Good morning{name_greeting}!)\n\n"
        briefing += "ዛሬ ለእርስዎ የሚመጥኑ ምርቶችን አግኝተናል። ለመመልከት ይጠቅሙ። (Today we've found some products that might interest you. Take a look.)\n\n"
        briefing += "ሁሉም ትእዛዞች በጥሩ ሁኔታ እየተከናወኑ ናቸው። በትእዛዝዎ ላይ ለመከታተል ይጠይቁኝ። (All orders are processing well. Ask me to track your orders for updates.)"
        
        return briefing
