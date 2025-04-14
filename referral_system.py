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
    'first_deposit': 25,  # Points for when referred user makes first deposit
    'subscription': 30,  # Points for when referred user subscribes
    'first_order': 40,  # Points for referred user's first order
}

# Points to ETB conversion rate (100 points = 10 ETB)
POINTS_TO_ETB_RATE = 0.1

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
