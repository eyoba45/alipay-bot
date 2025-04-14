"""
Referral System for AliPay ETH
Handles referral code generation, point tracking, and reward management
"""
import os
import random
import string
import logging
from datetime import datetime
from sqlalchemy import func
from models import User, Referral, ReferralReward
from database import get_session, safe_close_session

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("referral_system")

# Referral point values
REFERRAL_POINTS = {
    'signup': 50,           # Points for referring a user who signs up
    'deposit': 25,          # Points for referring a user who makes a deposit
    'subscription': 30,     # Points for referring a user who subscribes
    'order': 40,            # Points for referring a user who places an order
    'bonus': 10,            # Bonus points for special actions
}

# Points to ETB conversion rate (e.g., 100 points = 10 ETB)
POINTS_TO_ETB_RATE = 10  # 10 points = 1 ETB

def generate_referral_code(user_id, length=8):
    """Generate a unique referral code for a user"""
    # Use a consistent prefix to make codes recognizable
    prefix = "ALI"
    # Get a few characters from the user ID for personalization
    id_part = str(user_id).zfill(4)[-3:]
    # Add random characters for uniqueness
    random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length-len(prefix)-len(id_part)))
    
    code = f"{prefix}{id_part}{random_part}"
    
    # Verify the code is unique
    session = get_session()
    try:
        existing = session.query(User).filter_by(referral_code=code).first()
        if existing:
            # If code exists, recursively generate a new one
            return generate_referral_code(user_id, length)
        return code
    finally:
        safe_close_session(session)

def assign_referral_code(user_id):
    """Assign a unique referral code to a user if they don't have one"""
    session = get_session()
    try:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            logger.error(f"User with ID {user_id} not found")
            return None
            
        if user.referral_code:
            return user.referral_code
            
        # Generate a new referral code
        referral_code = generate_referral_code(user_id)
        user.referral_code = referral_code
        session.commit()
        logger.info(f"Assigned referral code {referral_code} to user {user_id}")
        
        return referral_code
    except Exception as e:
        logger.error(f"Error assigning referral code: {e}")
        session.rollback()
        return None
    finally:
        safe_close_session(session)

def get_referral_url(referral_code):
    """Get a shareable referral URL with the given code"""
    bot_username = os.environ.get('TELEGRAM_BOT_USERNAME', 'your_bot_username')
    return f"https://t.me/{bot_username}?start={referral_code}"

def process_referral_code(referred_telegram_id, referral_code):
    """Process a referral when a new user signs up with a referral code"""
    session = get_session()
    try:
        # Check if the referred user exists
        referred_user = session.query(User).filter_by(telegram_id=referred_telegram_id).first()
        if not referred_user:
            logger.error(f"Referred user with Telegram ID {referred_telegram_id} not found")
            return False, "Referred user not found"
            
        # Check if the referred user already has a referrer
        if referred_user.referred_by_id:
            logger.warning(f"User {referred_telegram_id} already has a referrer")
            return False, "User already has a referrer"
            
        # Find the referrer by the code
        referrer = session.query(User).filter_by(referral_code=referral_code).first()
        if not referrer:
            logger.error(f"No user found with referral code {referral_code}")
            return False, "Invalid referral code"
            
        # Prevent self-referrals
        if referrer.id == referred_user.id:
            logger.warning(f"User {referred_telegram_id} attempted to refer themselves")
            return False, "You cannot refer yourself"
            
        # Set the referrer for the user
        referred_user.referred_by_id = referrer.id
        
        # Create a referral record
        referral = Referral(
            referrer_id=referrer.id,
            referred_id=referred_user.id,
            referral_code=referral_code,
            status='pending'
        )
        session.add(referral)
        session.commit()
        logger.info(f"Created referral: User {referrer.id} referred user {referred_user.id}")
        
        return True, referral
    except Exception as e:
        logger.error(f"Error processing referral: {e}")
        session.rollback()
        return False, f"Error: {str(e)}"
    finally:
        safe_close_session(session)

def complete_referral(referral_id):
    """Mark a referral as completed and award points"""
    session = get_session()
    try:
        referral = session.query(Referral).filter_by(id=referral_id).first()
        if not referral:
            logger.error(f"Referral with ID {referral_id} not found")
            return False, "Referral not found"
            
        if referral.status == 'completed' or referral.status == 'rewarded':
            logger.warning(f"Referral {referral_id} already marked as {referral.status}")
            return False, f"Referral already {referral.status}"
            
        # Get the referrer
        referrer = session.query(User).filter_by(id=referral.referrer_id).first()
        if not referrer:
            logger.error(f"Referrer with ID {referral.referrer_id} not found")
            return False, "Referrer not found"
            
        # Award signup points
        referrer.referral_points += REFERRAL_POINTS['signup']
        
        # Create a reward record
        reward = ReferralReward(
            user_id=referrer.id,
            referral_id=referral.id,
            points=REFERRAL_POINTS['signup'],
            reward_type='signup',
            description=f"Earned for referring a new user who completed registration"
        )
        session.add(reward)
        
        # Update referral status
        referral.status = 'completed'
        referral.completed_at = datetime.utcnow()
        
        session.commit()
        logger.info(f"Completed referral {referral_id} and awarded {REFERRAL_POINTS['signup']} points to user {referrer.id}")
        
        return True, reward
    except Exception as e:
        logger.error(f"Error completing referral: {e}")
        session.rollback()
        return False, f"Error: {str(e)}"
    finally:
        safe_close_session(session)

def award_referral_points(user_id, referral_id, reward_type, description=None):
    """Award points to a user for a specific referral action"""
    if reward_type not in REFERRAL_POINTS:
        logger.error(f"Invalid reward type: {reward_type}")
        return False, "Invalid reward type"
        
    points = REFERRAL_POINTS[reward_type]
    
    session = get_session()
    try:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            logger.error(f"User with ID {user_id} not found")
            return False, "User not found"
            
        # Check if referral exists
        referral = None
        if referral_id:
            referral = session.query(Referral).filter_by(id=referral_id).first()
            if not referral:
                logger.error(f"Referral with ID {referral_id} not found")
                return False, "Referral not found"
                
        # Get a descriptive message if none provided
        if not description:
            descriptions = {
                'signup': "New user registration",
                'deposit': "Referred user made a deposit",
                'subscription': "Referred user paid for subscription",
                'order': "Referred user placed an order",
                'bonus': "Bonus points"
            }
            description = descriptions.get(reward_type, f"Points for {reward_type}")
            
        # Award points
        user.referral_points += points
        
        # Create reward record
        reward = ReferralReward(
            user_id=user.id,
            referral_id=referral_id,
            points=points,
            reward_type=reward_type,
            description=description
        )
        session.add(reward)
        
        # If this is an order or deposit, mark referral as rewarded
        if referral and reward_type in ['order', 'deposit', 'subscription']:
            referral.status = 'rewarded'
            
        session.commit()
        logger.info(f"Awarded {points} {reward_type} points to user {user_id}")
        
        return True, reward
    except Exception as e:
        logger.error(f"Error awarding points: {e}")
        session.rollback()
        return False, f"Error: {str(e)}"
    finally:
        safe_close_session(session)

def check_user_points_balance(user_id):
    """Get user's current points balance and redemption value"""
    session = get_session()
    try:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            logger.error(f"User with ID {user_id} not found")
            return None
            
        # Calculate ETB value
        etb_value = user.referral_points / POINTS_TO_ETB_RATE
        
        return {
            'user_id': user.id,
            'points': user.referral_points,
            'etb_value': etb_value,
            'referral_code': user.referral_code,
            'referral_url': get_referral_url(user.referral_code) if user.referral_code else None
        }
    except Exception as e:
        logger.error(f"Error checking points balance: {e}")
        return None
    finally:
        safe_close_session(session)

def get_user_referrals(user_id):
    """Get all referrals made by a user"""
    session = get_session()
    try:
        referrals = session.query(Referral).filter_by(referrer_id=user_id).all()
        result = []
        
        for referral in referrals:
            referred_user = session.query(User).filter_by(id=referral.referred_id).first()
            if referred_user:
                result.append({
                    'id': referral.id,
                    'referred_name': referred_user.name,
                    'referred_id': referred_user.id,
                    'status': referral.status,
                    'created_at': referral.created_at,
                    'completed_at': referral.completed_at
                })
        
        return result
    except Exception as e:
        logger.error(f"Error getting user referrals: {e}")
        return []
    finally:
        safe_close_session(session)

def get_referral_rewards(user_id):
    """Get all rewards earned by a user"""
    session = get_session()
    try:
        rewards = session.query(ReferralReward).filter_by(user_id=user_id).order_by(ReferralReward.created_at.desc()).all()
        return [
            {
                'id': reward.id,
                'points': reward.points,
                'reward_type': reward.reward_type,
                'description': reward.description,
                'created_at': reward.created_at
            }
            for reward in rewards
        ]
    except Exception as e:
        logger.error(f"Error getting user rewards: {e}")
        return []
    finally:
        safe_close_session(session)

def redeem_points(user_id, points_to_redeem):
    """Redeem points for balance"""
    session = get_session()
    try:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            logger.error(f"User with ID {user_id} not found")
            return False, "User not found"
            
        # Check if user has enough points
        if user.referral_points < points_to_redeem:
            logger.warning(f"User {user_id} tried to redeem {points_to_redeem} points but only has {user.referral_points}")
            return False, "Not enough points"
            
        # Calculate ETB value
        etb_value = points_to_redeem / POINTS_TO_ETB_RATE
        
        # Update user balance
        user.referral_points -= points_to_redeem
        user.balance += etb_value
        
        # Record the reward
        reward = ReferralReward(
            user_id=user.id,
            points=-points_to_redeem,
            reward_type='redemption',
            description=f"Redeemed {points_to_redeem} points for {etb_value:.2f} ETB"
        )
        session.add(reward)
        
        session.commit()
        logger.info(f"User {user_id} redeemed {points_to_redeem} points for {etb_value:.2f} ETB")
        
        return True, {
            'redeemed_points': points_to_redeem,
            'etb_value': etb_value,
            'remaining_points': user.referral_points,
            'new_balance': user.balance
        }
    except Exception as e:
        logger.error(f"Error redeeming points: {e}")
        session.rollback()
        return False, f"Error: {str(e)}"
    finally:
        safe_close_session(session)

def get_top_referrers(limit=10):
    """Get top users by referral count"""
    session = get_session()
    try:
        # Count referrals per referrer
        result = session.query(
            Referral.referrer_id,
            func.count(Referral.id).label('referral_count')
        ).group_by(Referral.referrer_id) \
         .order_by(func.count(Referral.id).desc()) \
         .limit(limit) \
         .all()
         
        top_referrers = []
        for referrer_id, count in result:
            user = session.query(User).filter_by(id=referrer_id).first()
            if user:
                top_referrers.append({
                    'id': user.id,
                    'name': user.name,
                    'referral_count': count,
                    'points': user.referral_points
                })
                
        return top_referrers
    except Exception as e:
        logger.error(f"Error getting top referrers: {e}")
        return []
    finally:
        safe_close_session(session)
