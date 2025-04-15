"""
Referral System for AliPay_ETH Bot

This module handles all referral-related functionality including:
- Generating and managing referral codes
- Tracking referrals
- Processing rewards
- Handling points redemption
"""

import os
import random
import string
import logging
from datetime import datetime

from sqlalchemy import and_
from database import get_session, safe_close_session
from models import User, Referral, ReferralReward, Transaction, UserBalance

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# Constants for reward points
REWARD_POINTS = {
    'registration': 50,  # Points for referring someone who registers
    # No longer giving points for these actions
    'first_deposit': 0,  # No points for deposits
    'subscription': 0,  # No points for subscription
    'first_order': 0,  # No points for orders
}

# Points to ETB conversion rate (1 point = 1 ETB)
POINTS_TO_ETB_RATE = 1.0

# Referral achievement badges with hover effects
REFERRAL_BADGES = [
    {
        'name': 'Beginner Referrer',
        'icon': '🥉',
        'referrals_required': 1,
        'hover_text': 'You invited your first friend! Keep going!',
        'color': '#CD7F32'  # Bronze color
    },
    {
        'name': 'Rising Referrer',
        'icon': '🥈',
        'referrals_required': 3,
        'hover_text': 'You\'ve invited 3 friends! Great progress!',
        'color': '#C0C0C0'  # Silver color
    },
    {
        'name': 'Champion Referrer',
        'icon': '🥇',
        'referrals_required': 5,
        'hover_text': 'Amazing! You\'ve invited 5 friends!',
        'color': '#FFD700'  # Gold color
    },
    {
        'name': 'Elite Referrer',
        'icon': '💎',
        'referrals_required': 10,
        'hover_text': 'Incredible! You\'re among our top referrers with 10+ invites!',
        'color': '#00BFFF'  # Diamond blue color
    },
    {
        'name': 'Legendary Referrer',
        'icon': '👑',
        'referrals_required': 20,
        'hover_text': 'Legendary status achieved with 20+ invites! You\'re amazing!',
        'color': '#FFD700'  # Crown gold color
    }
]

def assign_referral_code(user_id, length=8):
    """
    Generate a unique referral code for a user
    
    Args:
        user_id: The user's database ID
        length: Length of the referral code (default 8)
        
    Returns:
        str: A unique referral code
    """
    session = None
    try:
        # Create a random code with uppercase letters and numbers
        characters = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(random.choices(characters, k=length))
            
            # Check if the code already exists
            session = get_session()
            existing = session.query(User).filter_by(referral_code=code).first()
            if not existing:
                # Update the user with the new code
                user = session.query(User).filter_by(id=user_id).first()
                if user:
                    user.referral_code = code
                    session.commit()
                    logger.info(f"Created referral code {code} for user {user_id}")
                return code
    except Exception as e:
        logger.error(f"Error assigning referral code: {e}")
        if session:
            session.rollback()
        return None
    finally:
        safe_close_session(session)

def get_referral_url(referral_code):
    """
    Generate a referral URL with the given code
    
    Args:
        referral_code: The user's referral code
        
    Returns:
        str: A Telegram bot start URL with the referral code
    """
    bot_username = os.environ.get('TELEGRAM_BOT_USERNAME', 'alipay_eth_bot')
    return f"https://t.me/{bot_username}?start={referral_code}"

def process_referral(referrer_id, referred_user_id, action_type):
    """
    Process a referral action and award points
    
    Args:
        referrer_id: ID of the user who referred
        referred_user_id: ID of the user being referred
        action_type: Type of action ('registration', 'first_deposit', 'subscription', 'first_order')
        
    Returns:
        bool: True if successful, False otherwise
    """
    session = None
    try:
        if action_type not in REWARD_POINTS:
            logger.error(f"Invalid referral action type: {action_type}")
            return False
            
        points = REWARD_POINTS[action_type]
        session = get_session()
        
        # Get the referrer user
        referrer = session.query(User).filter_by(id=referrer_id).first()
        if not referrer:
            logger.error(f"Referrer with ID {referrer_id} not found")
            return False
            
        # Get the referred user
        referred = session.query(User).filter_by(id=referred_user_id).first()
        if not referred:
            logger.error(f"Referred user with ID {referred_user_id} not found")
            return False
            
        # Check if this specific reward has already been given
        existing_reward = session.query(ReferralReward).filter(
            and_(
                ReferralReward.referrer_id == referrer_id,
                ReferralReward.referred_id == referred_user_id,
                ReferralReward.reward_type == action_type
            )
        ).first()
        
        if existing_reward:
            logger.info(f"Reward for {action_type} already given for referral {referrer_id} -> {referred_user_id}")
            return False
            
        # Create the reward record
        reward = ReferralReward(
            referrer_id=referrer_id,
            referred_id=referred_user_id,
            points=points,
            reward_type=action_type,
            description=f"Received {points} points for {referred.name}'s {action_type.replace('_', ' ')}"
        )
        session.add(reward)
        
        # Update referrer's points
        referrer.referral_points = (referrer.referral_points or 0) + points
        
        # Update referral status if needed
        referral = session.query(Referral).filter(
            and_(
                Referral.referrer_id == referrer_id,
                Referral.referred_id == referred_user_id
            )
        ).first()
        
        if referral:
            referral.status = 'rewarded'
            
        session.commit()
        logger.info(f"Awarded {points} points to user {referrer_id} for referral action {action_type}")
        return True
        
    except Exception as e:
        logger.error(f"Error processing referral: {e}")
        if session:
            session.rollback()
        return False
    finally:
        safe_close_session(session)

def check_and_process_registration_referral(user_id, referral_code):
    """
    Check if a user was referred by a valid referral code and process the reward
    
    Args:
        user_id: The new user's ID
        referral_code: The referral code used
        
    Returns:
        bool: True if successful, False otherwise
    """
    session = None
    try:
        session = get_session()
        
        # Find the referrer by code
        referrer = session.query(User).filter_by(referral_code=referral_code).first()
        if not referrer:
            logger.info(f"No user found with referral code {referral_code}")
            return False
            
        # Make sure user isn't referring themselves
        if referrer.id == user_id:
            logger.warning(f"User {user_id} attempted to refer themselves")
            return False
            
        # Check if this referral already exists
        existing = session.query(Referral).filter(
            and_(
                Referral.referrer_id == referrer.id,
                Referral.referred_id == user_id
            )
        ).first()
        
        if existing:
            logger.info(f"Referral already exists: {referrer.id} -> {user_id}")
            return False
            
        # Create the referral record
        referral = Referral(
            referrer_id=referrer.id,
            referred_id=user_id,
            referral_date=datetime.now(),
            status='completed'
        )
        session.add(referral)
        session.commit()
        
        # Process the registration reward
        success = process_referral(referrer.id, user_id, 'registration')
        
        return success
        
    except Exception as e:
        logger.error(f"Error checking registration referral: {e}")
        if session:
            session.rollback()
        return False
    finally:
        safe_close_session(session)

def get_user_referrals(user_id):
    """
    Get a list of all users referred by a given user
    
    Args:
        user_id: The user's ID
        
    Returns:
        list: List of referral details
    """
    session = None
    try:
        session = get_session()
        query = """
        SELECT 
            r.id, 
            r.referred_id, 
            u.name as referred_name,
            r.referral_date,
            r.status
        FROM referrals r
        JOIN users u ON r.referred_id = u.id
        WHERE r.referrer_id = :user_id
        ORDER BY r.referral_date DESC
        """
        
        result = session.execute(query, {'user_id': user_id})
        referrals = []
        
        for row in result:
            referrals.append({
                'id': row.id,
                'referred_id': row.referred_id,
                'referred_name': row.referred_name,
                'referral_date': row.referral_date,
                'status': row.status
            })
            
        return referrals
        
    except Exception as e:
        logger.error(f"Error getting user referrals: {e}")
        return []
    finally:
        safe_close_session(session)

def get_referral_rewards(user_id):
    """
    Get a list of rewards earned by a user from referrals
    
    Args:
        user_id: The user's ID
        
    Returns:
        list: List of reward details
    """
    session = None
    try:
        session = get_session()
        query = """
        SELECT 
            rr.id,
            rr.points,
            rr.reward_type,
            rr.description,
            rr.created_at,
            u.name as referred_name
        FROM referral_rewards rr
        JOIN users u ON rr.referred_id = u.id
        WHERE rr.referrer_id = :user_id
        ORDER BY rr.created_at DESC
        """
        
        result = session.execute(query, {'user_id': user_id})
        rewards = []
        
        for row in result:
            rewards.append({
                'id': row.id,
                'points': row.points,
                'reward_type': row.reward_type,
                'description': row.description,
                'created_at': row.created_at,
                'referred_name': row.referred_name
            })
            
        return rewards
        
    except Exception as e:
        logger.error(f"Error getting referral rewards: {e}")
        return []
    finally:
        safe_close_session(session)

def check_user_points_balance(user_id):
    """
    Check a user's current referral points balance and ETB value
    
    Args:
        user_id: The user's ID
        
    Returns:
        dict: User's points details
    """
    session = None
    try:
        session = get_session()
        user = session.query(User).filter_by(id=user_id).first()
        
        if not user:
            return {'points': 0, 'etb_value': 0.0}
            
        points = user.referral_points or 0
        etb_value = points * POINTS_TO_ETB_RATE
        
        return {
            'points': points,
            'etb_value': etb_value
        }
        
    except Exception as e:
        logger.error(f"Error checking points balance: {e}")
        return {'points': 0, 'etb_value': 0.0}
    finally:
        safe_close_session(session)

def process_referral_code(user_id, referral_code):
    """
    Process a referral code when a new user registers
    
    Args:
        user_id: The new user's telegram_id
        referral_code: The referral code used
        
    Returns:
        tuple: (success, result_obj)
    """
    session = None
    try:
        session = get_session()
        
        # Get the user database record
        user = session.query(User).filter_by(telegram_id=user_id).first()
        if not user:
            logger.error(f"User with telegram_id {user_id} not found")
            return False, None
            
        # Process the referral
        success = check_and_process_registration_referral(user.id, referral_code)
        
        if success:
            # Find the referrer by code
            referrer = session.query(User).filter_by(referral_code=referral_code).first()
            if referrer:
                logger.info(f"Successfully processed referral: {referrer.id} -> {user.id}")
                return True, referrer
                
        return False, None
        
    except Exception as e:
        logger.error(f"Error processing referral code: {e}")
        return False, None
    finally:
        safe_close_session(session)
        
def complete_referral(referrer_id):
    """
    Complete a referral by awarding registration points
    
    Args:
        referrer_id: The ID of the user who made the referral
        
    Returns:
        tuple: (success, points_awarded)
    """
    # Only award points for successful registration - no points for other actions
    # This matches the updated reward structure where only registration rewards points
    return True, REWARD_POINTS['registration']

def get_user_badge(user_id):
    """
    Get a user's current referral badge based on number of successful referrals
    
    Args:
        user_id: The user's ID
        
    Returns:
        dict: Badge details including name, icon, hover text and color
    """
    session = None
    try:
        session = get_session()
        
        # Count successful referrals
        query = """
        SELECT COUNT(*) as referral_count
        FROM referrals
        WHERE referrer_id = :user_id
        AND status = 'completed'
        """
        
        result = session.execute(query, {'user_id': user_id}).fetchone()
        referral_count = result.referral_count if result else 0
        
        # Find the highest badge earned
        earned_badge = None
        for badge in reversed(REFERRAL_BADGES):
            if referral_count >= badge['referrals_required']:
                earned_badge = badge
                break
                
        # If no badge earned yet, return the first one as "locked"
        if not earned_badge:
            first_badge = REFERRAL_BADGES[0].copy()
            first_badge['locked'] = True
            first_badge['hover_text'] = f"Invite 1 friend to earn this badge!"
            return first_badge
            
        # Return badge with additional referral count info
        badge_with_count = earned_badge.copy()
        badge_with_count['referral_count'] = referral_count
        
        # Calculate progress to next badge
        current_index = REFERRAL_BADGES.index(earned_badge)
        if current_index < len(REFERRAL_BADGES) - 1:
            next_badge = REFERRAL_BADGES[current_index + 1]
            needed = next_badge['referrals_required'] - referral_count
            badge_with_count['next_badge'] = next_badge['name']
            badge_with_count['needed_for_next'] = needed
            
        return badge_with_count
        
    except Exception as e:
        logger.error(f"Error getting user badge: {e}")
        return REFERRAL_BADGES[0]
    finally:
        safe_close_session(session)
        
def generate_badge_html(user_id):
    """
    Generate HTML for user's badge with hover effect
    
    Args:
        user_id: The user's ID
        
    Returns:
        str: HTML string with badge and hover effect
    """
    badge = get_user_badge(user_id)
    
    if badge.get('locked'):
        # Locked badge (gray with lock emoji)
        html = f"""
<span style="position:relative; display:inline-block; cursor:pointer;" 
      onmouseover="this.querySelector('.badge-tooltip').style.display='block'" 
      onmouseout="this.querySelector('.badge-tooltip').style.display='none'">
    <span style="font-size:22px; opacity:0.5;">{badge['icon']} 🔒</span>
    <span class="badge-tooltip" style="display:none; position:absolute; bottom:100%; left:50%; transform:translateX(-50%); 
           background-color:#f8f9fa; color:#333; padding:8px 12px; border-radius:6px; 
           box-shadow:0 2px 8px rgba(0,0,0,0.2); white-space:nowrap; z-index:1000; 
           font-size:14px; width:200px; text-align:center;">
        <b>{badge['name']}</b><br>{badge['hover_text']}
    </span>
</span>
"""
    else:
        # Earned badge with color and hover effect
        next_badge_text = ""
        if badge.get('next_badge'):
            next_badge_text = f"<br>🔼 {badge['needed_for_next']} more to reach {badge['next_badge']}!"
        
        hover_info = f"{badge['hover_text']}<br>🌟 You've referred {badge['referral_count']} friends!{next_badge_text}"
        
        html = f"""
<span style="position:relative; display:inline-block; cursor:pointer;" 
      onmouseover="this.querySelector('.badge-tooltip').style.display='block'" 
      onmouseout="this.querySelector('.badge-tooltip').style.display='none'">
    <span style="font-size:22px; color:{badge['color']};">{badge['icon']}</span>
    <span class="badge-tooltip" style="display:none; position:absolute; bottom:100%; left:50%; transform:translateX(-50%); 
           background-color:#f8f9fa; color:#333; padding:8px 12px; border-radius:6px; 
           box-shadow:0 2px 8px rgba(0,0,0,0.2); white-space:nowrap; z-index:1000; 
           font-size:14px; width:200px; text-align:center;">
        <b>{badge['name']}</b><br>{hover_info}
    </span>
</span>
"""
    return html

def redeem_points(user_id, points_to_redeem):
    """
    Redeem referral points for ETB account balance
    
    Args:
        user_id: The user's ID
        points_to_redeem: Number of points to redeem
        
    Returns:
        tuple: (success, result_dict)
    """
    session = None
    try:
        if points_to_redeem < 100:
            logger.warning(f"Attempted to redeem {points_to_redeem} points, which is below minimum")
            return False, None
            
        session = get_session()
        user = session.query(User).filter_by(id=user_id).first()
        
        if not user or not user.referral_points or user.referral_points < points_to_redeem:
            logger.warning(f"User {user_id} has insufficient points for redemption")
            return False, None
            
        # Calculate ETB value
        etb_value = points_to_redeem * POINTS_TO_ETB_RATE
        
        # Update user points
        user.referral_points -= points_to_redeem
        
        # Update user balance
        balance = session.query(UserBalance).filter_by(user_id=user_id).first()
        
        if not balance:
            # Create new balance record if none exists
            balance = UserBalance(
                user_id=user_id,
                balance=etb_value
            )
            session.add(balance)
        else:
            # Update existing balance
            balance.balance += etb_value
            
        # Create transaction record
        transaction = Transaction(
            user_id=user_id,
            amount=etb_value,
            transaction_type='referral_redemption',
            description=f"Redeemed {points_to_redeem} referral points for {etb_value:.2f} ETB",
            status='completed'
        )
        session.add(transaction)
        
        session.commit()
        logger.info(f"User {user_id} redeemed {points_to_redeem} points for {etb_value:.2f} ETB")
        
        # Return success with details
        return True, {
            'redeemed_points': points_to_redeem,
            'etb_value': etb_value,
            'remaining_points': user.referral_points,
            'new_balance': balance.balance
        }
        
    except Exception as e:
        logger.error(f"Error redeeming points: {e}")
        if session:
            session.rollback()
        return False, None
    finally:
        safe_close_session(session)
