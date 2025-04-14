from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, BigInteger, ForeignKey, Text, Boolean
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)

    subscription_date = Column(DateTime, default=datetime.utcnow)
    last_subscription_reminder = Column(DateTime, nullable=True)

    name = Column(String, nullable=False)
    phone = Column(String)
    address = Column(String)
    balance = Column(Float, default=0.0)
    
    # Referral system fields
    referral_code = Column(String, unique=True, nullable=True)
    referred_by_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    referral_points = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    orders = relationship("Order", back_populates="user")
    pending_deposits = relationship("PendingDeposit", back_populates="user")
    companion_profile = relationship("CompanionProfile", back_populates="user", uselist=False)
    companion_interactions = relationship("CompanionInteraction", back_populates="user")
    
    # Referral relationships
    referred_users = relationship("User", backref="referred_by", remote_side=[id])
    referral_rewards = relationship("ReferralReward", back_populates="user")
    referrals_made = relationship("Referral", back_populates="referrer", foreign_keys="Referral.referrer_id")
    referrals_received = relationship("Referral", back_populates="referred", foreign_keys="Referral.referred_id")

    def __repr__(self):
        return f"<User(telegram_id={self.telegram_id}, name='{self.name}', balance=${self.balance:.2f})>"

class Order(Base):
    __tablename__ = 'orders'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    order_number = Column(Integer, nullable=False)  # Order number for this user
    product_link = Column(String, nullable=False)
    order_id = Column(String)  # AliExpress order ID
    tracking_number = Column(String)
    status = Column(String, default='Processing')
    amount = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship with user
    user = relationship("User", back_populates="orders")

    def __repr__(self):
        return f"<Order(id={self.id}, user_id={self.user_id}, order_number={self.order_number}, status='{self.status}', amount=${self.amount:.2f if self.amount else 0.00})>"

    def update_attributes(self, **kwargs):
        """
        Update attributes of the Order object
        This helps when manually updating order attributes
        """
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        return self

class PendingApproval(Base):
    __tablename__ = 'pending_approvals'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    address = Column(String, nullable=False)
    payment_status = Column(String, default='pending')  # pending, paid
    tx_ref = Column(String, unique=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<PendingApproval(telegram_id={self.telegram_id}, name='{self.name}', status='{self.payment_status}')>"

class PendingDeposit(Base):
    __tablename__ = 'pending_deposits'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    amount = Column(Float, nullable=False)
    tx_ref = Column(String, unique=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default='Processing')

    # Relationship with user
    user = relationship("User", back_populates="pending_deposits")

    def __repr__(self):
        return f"<PendingDeposit(user_id={self.user_id}, amount=${self.amount:.2f})>"

class CompanionInteraction(Base):
    __tablename__ = 'companion_interactions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    message_text = Column(Text, nullable=False)
    interaction_type = Column(String, nullable=False)  # 'greeting', 'question', 'recommendation', etc.
    sentiment = Column(String, nullable=True)  # 'positive', 'negative', 'neutral'
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship with user
    user = relationship("User", back_populates="companion_interactions")
    
    def __repr__(self):
        return f"<CompanionInteraction(user_id={self.user_id}, type='{self.interaction_type}')>"

class CompanionProfile(Base):
    __tablename__ = 'companion_profiles'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, unique=True)
    companion_name = Column(String, default="Selam")
    relationship_level = Column(Integer, default=1)  # 1-10 scale of relationship development
    preferred_language = Column(String, default="amharic")
    favorite_categories = Column(String, nullable=True)  # Comma-separated list
    interaction_style = Column(String, default="friendly")  # 'friendly', 'professional', 'casual'
    last_interaction = Column(DateTime, nullable=True)
    morning_brief = Column(Boolean, default=True)  # Whether to send morning briefings
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship with user
    user = relationship("User", back_populates="companion_profile")
    
    def __repr__(self):
        return f"<CompanionProfile(user_id={self.user_id}, name='{self.companion_name}', relationship_level={self.relationship_level})>"

class Referral(Base):
    __tablename__ = 'referrals'
    
    id = Column(Integer, primary_key=True)
    referrer_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    referred_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    referral_code = Column(String, nullable=False)
    status = Column(String, default='pending')  # pending, completed, rewarded
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    referrer = relationship("User", foreign_keys=[referrer_id], back_populates="referrals_made")
    referred = relationship("User", foreign_keys=[referred_id], back_populates="referrals_received")
    
    def __repr__(self):
        return f"<Referral(referrer_id={self.referrer_id}, referred_id={self.referred_id}, status='{self.status}')>"

class ReferralReward(Base):
    __tablename__ = 'referral_rewards'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    referral_id = Column(Integer, ForeignKey('referrals.id'), nullable=True)
    points = Column(Integer, nullable=False)
    reward_type = Column(String, nullable=False)  # 'signup', 'deposit', 'subscription', 'order', 'bonus'
    description = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="referral_rewards")
    referral = relationship("Referral", backref="rewards")
    
    def __repr__(self):
        return f"<ReferralReward(user_id={self.user_id}, points={self.points}, type='{self.reward_type}')>"

class UserBalance(Base):
    __tablename__ = 'user_balances'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, unique=True)
    balance = Column(Float, default=0.0)
    last_deposit_date = Column(DateTime, nullable=True)
    last_spend_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    user = relationship("User", backref="user_balance")
    
    def __repr__(self):
        return f"<UserBalance(user_id={self.user_id}, balance=${self.balance:.2f})>"

class Transaction(Base):
    __tablename__ = 'transactions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    amount = Column(Float, nullable=False)
    transaction_type = Column(String, nullable=False)  # deposit, order_payment, refund, subscription, referral_redemption
    description = Column(String, nullable=False)
    reference = Column(String, nullable=True)  # External reference number
    status = Column(String, default='completed')  # pending, completed, failed, refunded
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    user = relationship("User", backref="transactions")
    
    def __repr__(self):
        return f"<Transaction(user_id={self.user_id}, type='{self.transaction_type}', amount=${self.amount:.2f})>"
