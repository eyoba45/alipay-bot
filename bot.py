@bot.message_handler(func=lambda msg: msg.text == '🎁 Referrals')
def show_referrals(message):
    """Handle referrals button press"""
    chat_id = message.chat.id
    session = None
    try:
        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()
        
        if not user:
            bot.send_message(
                chat_id,
                "❌ You need to be registered to access referrals.",
                reply_markup=create_main_menu(is_registered=False)
            )
            return
            
        # Import referral system functions
        from referral_system import (
            assign_referral_code, 
            get_referral_url, 
            get_user_referrals,
            check_user_points_balance, 
            get_referral_rewards
        )
        
        # Make sure user has a referral code
        if not user.referral_code:
            user.referral_code = assign_referral_code(user.id)
            session.commit()
            
        # Get referral stats
        referral_stats = check_user_points_balance(user.id)
        referrals = get_user_referrals(user.id)
        rewards = get_referral_rewards(user.id)
        
        referral_url = get_referral_url(user.referral_code)
        
        # Display basic referral information
        header = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🎁 <b>YOUR REFERRAL PROGRAM</b> 🎁  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>📊 YOUR REFERRAL STATS:</b>
• Referral Points: <code>{referral_stats['points']}</code> points
• Points Value: <code>{referral_stats['etb_value']:.2f}</code> ETB
• Total Referrals: <code>{len(referrals)}</code> friends

<b>📱 YOUR REFERRAL INFO:</b>
• Code: <code>{user.referral_code}</code>
• Link: <code>{referral_url}</code>

<b>📣 HOW TO EARN:</b>
• Get 50 points for each friend who registers (value: 5 ETB)
• Get 25 points when they make their first deposit
• Get 30 points when they subscribe
• Get 40 points when they place their first order

<i>Points can be redeemed for account balance!</i>
"""
        bot.send_message(chat_id, header, parse_mode='HTML')
        
        # Display referral menu with options
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton("📊 Show My Referrals", callback_data="show_my_referrals"),
            InlineKeyboardButton("📜 Show Reward History", callback_data="show_reward_history"),
            InlineKeyboardButton("💰 Redeem Points for Balance", callback_data="redeem_points")
        )
        
        bot.send_message(
            chat_id, 
            "🎁 <b>REFERRAL MENU:</b>\nSelect an option below:",
            reply_markup=markup,
            parse_mode='HTML'
        )
    
    except Exception as e:
        logger.error(f"Error showing referrals: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(
            chat_id, 
            "Sorry, there was an error loading your referrals. Please try again.",
            reply_markup=create_main_menu(True)
        )
    finally:
        safe_close_session(session)

@bot.callback_query_handler(func=lambda call: call.data in ['show_my_referrals', 'show_reward_history', 'redeem_points'])
def handle_referral_callbacks(call):
    """Handle referral menu callbacks"""
    chat_id = call.message.chat.id
    callback_data = call.data
    session = None
    
    try:
        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()
        
        if not user:
            bot.answer_callback_query(call.id, "You need to be registered first")
            return
            
        # Import referral system functions
        from referral_system import get_user_referrals, get_referral_rewards, check_user_points_balance
        
        if callback_data == 'show_my_referrals':
            # Show list of users referred
            referrals = get_user_referrals(user.id)
            
            if not referrals:
                bot.answer_callback_query(call.id)
                bot.send_message(
                    chat_id,
                    """
🔍 <b>YOUR REFERRALS</b>

You haven't referred any users yet. 
Share your referral code or link with friends to earn points!
                    """,
                    parse_mode='HTML'
                )
                return
                
            # Format referral list message
            referral_msg = """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   👥 <b>YOUR REFERRALS</b> 👥  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

"""
            for i, ref in enumerate(referrals, 1):
                status_emoji = "✅" if ref['status'] == 'completed' or ref['status'] == 'rewarded' else "⏳"
                referral_msg += f"{i}. {status_emoji} <b>{ref['referred_name']}</b> - {ref['status'].title()}\n"
                
            referral_msg += "\n<i>✅ = Active, ⏳ = Pending</i>"
            
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, referral_msg, parse_mode='HTML')
            
        elif callback_data == 'show_reward_history':
            # Show reward history
            rewards = get_referral_rewards(user.id)
            
            if not rewards:
                bot.answer_callback_query(call.id)
                bot.send_message(
                    chat_id,
                    """
📜 <b>REWARD HISTORY</b>

You haven't earned any rewards yet.
Refer friends to start earning points!
                    """,
                    parse_mode='HTML'
                )
                return
                
            # Format rewards message
            rewards_msg = """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📜 <b>REWARD HISTORY</b> 📜  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

"""
            # Show the 5 most recent rewards
            for i, reward in enumerate(rewards[:5], 1):
                date_str = reward['created_at'].strftime('%d/%m/%Y')
                rewards_msg += f"{i}. <b>{reward['points']} points</b> - {reward['description']} ({date_str})\n"
                
            if len(rewards) > 5:
                rewards_msg += f"\n<i>+ {len(rewards) - 5} more rewards</i>"
                
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, rewards_msg, parse_mode='HTML')
            
        elif callback_data == 'redeem_points':
            # Initiate points redemption process
            stats = check_user_points_balance(user.id)
            
            if stats['points'] < 100:
                bot.answer_callback_query(call.id, "You need at least 100 points to redeem")
                return
                
            # Store state for redemption process
            user_states[chat_id] = 'waiting_for_redemption_amount'
            
            redemption_msg = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💰 <b>REDEEM POINTS</b> 💰  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>YOUR POINTS:</b> <code>{stats['points']}</code> points
<b>POINTS VALUE:</b> <code>{stats['etb_value']:.2f}</code> ETB

<b>REDEMPTION RATE:</b>
• 100 points = 10 ETB
• 200 points = 20 ETB
• 500 points = 50 ETB

Please enter the number of points you want to redeem (minimum 100):
"""
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, redemption_msg, parse_mode='HTML')
    
    except Exception as e:
        logger.error(f"Error handling referral callback: {e}")
        logger.error(traceback.format_exc())
        bot.answer_callback_query(call.id, "An error occurred. Please try again.")
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.chat.id in user_states and user_states[msg.chat.id] == 'waiting_for_redemption_amount')
def process_redemption_amount(message):
    """Process points redemption amount"""
    chat_id = message.chat.id
    session = None
    
    try:
        # Validate input is a number
        points_text = message.text.strip()
        if not points_text.isdigit():
            bot.send_message(
                chat_id,
                "❌ Please enter a valid number of points to redeem."
            )
            return
            
        points_to_redeem = int(points_text)
        
        # Check minimum redemption amount
        if points_to_redeem < 100:
            bot.send_message(
                chat_id,
                "❌ Minimum redemption amount is 100 points. Please enter a larger amount."
            )
            return
            
        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()
        
        if not user:
            bot.send_message(
                chat_id,
                "❌ Error finding your account. Please try again later.",
                reply_markup=create_main_menu(True)
            )
            return
            
        # Check if user has enough points
        if user.referral_points < points_to_redeem:
            bot.send_message(
                chat_id,
                f"❌ You only have {user.referral_points} points available. Please enter a smaller amount."
            )
            return
            
        # Import redemption function
        from referral_system import redeem_points
        
        # Process redemption
        success, result = redeem_points(user.id, points_to_redeem)
        
        if success:
            confirmation_msg = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>POINTS REDEEMED</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>REDEEMED:</b> <code>{result['redeemed_points']}</code> points
<b>VALUE ADDED:</b> <code>{result['etb_value']:.2f}</code> ETB
<b>POINTS REMAINING:</b> <code>{result['remaining_points']}</code>
<b>NEW BALANCE:</b> <code>{result['new_balance']:.2f}</code> ETB

Thank you for participating in our referral program!
"""
            bot.send_message(chat_id, confirmation_msg, parse_mode='HTML', reply_markup=create_main_menu(True))
        else:
            bot.send_message(
                chat_id,
                "❌ There was an error processing your redemption. Please try again later.",
                reply_markup=create_main_menu(True)
            )
            
        # Clear user state
        if chat_id in user_states:
            del user_states[chat_id]
            
    except Exception as e:
        logger.error(f"Error processing redemption: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(
            chat_id,
            "❌ An error occurred while processing your redemption. Please try again later.",
            reply_markup=create_main_menu(True)
        )
        
        # Clear user state
        if chat_id in user_states:
            del user_states[chat_id]
    finally:
        safe_close_session(session)
