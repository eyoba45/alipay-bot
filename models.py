from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, BigInteger, ForeignKey
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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    orders = relationship("Order", back_populates="user")
    pending_deposits = relationship("PendingDeposit", back_populates="user")

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
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<PendingApproval(telegram_id={self.telegram_id}, name='{self.name}')>"

class PendingDeposit(Base):
    __tablename__ = 'pending_deposits'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    amount = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default='Processing')

    # Relationship with user
    user = relationship("User", back_populates="pending_deposits")

    def __repr__(self):
        return f"<PendingDeposit(user_id={self.user_id}, amount=${self.amount:.2f})>"
