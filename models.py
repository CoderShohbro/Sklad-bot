from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
import datetime
from backend.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, index=True, nullable=False)
    username = Column(String, nullable=True)
    full_name = Column(String, nullable=False)
    role = Column(String, default="Skladchi")  # Admin or Skladchi
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    transactions = relationship("Transaction", back_populates="operator")

class Warehouse(Base):
    __tablename__ = "warehouses"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    location = Column(String, nullable=True)

    # Relationships
    stocks = relationship("Stock", back_populates="warehouse", cascade="all, delete-orphan")
    transactions = relationship("Transaction", foreign_keys="Transaction.warehouse_id", back_populates="warehouse")
    target_transactions = relationship("Transaction", foreign_keys="Transaction.target_warehouse_id", back_populates="target_warehouse")

class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)

    # Relationships
    products = relationship("Product", back_populates="category")

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    barcode = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    cost_price = Column(Float, default=0.0)      # Tannarxi
    selling_price = Column(Float, default=0.0)   # Sotilish narxi
    min_threshold = Column(Float, default=10.0)   # Minimal chegara (Warning limit)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    category = relationship("Category", back_populates="products")
    stocks = relationship("Stock", back_populates="product", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="product", cascade="all, delete")

class Stock(Base):
    """Skladlardagi joriy qoldiqlar"""
    __tablename__ = "stocks"

    product_id = Column(Integer, ForeignKey("products.id"), primary_key=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), primary_key=True)
    quantity = Column(Float, default=0.0)

    # Relationships
    product = relationship("Product", back_populates="stocks")
    warehouse = relationship("Warehouse", back_populates="stocks")

class Customer(Base):
    """Ustalar (Mijozlar) ro'yxati"""
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    balance = Column(Float, default=0.0)  # Qarzdorlik balansi: manfiy bo'lsa qarzdor, musbat bo'lsa oldindan to'lov qilgan
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    transactions = relationship("Transaction", back_populates="customer")

class Transaction(Base):
    """Kirim, chiqim, transfer va spisat tarixi"""
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False) # Source or main warehouse
    type = Column(String, nullable=False)  # Kirim, Chiqim, Transfer, Spisat
    quantity = Column(Float, nullable=False)
    cost_price = Column(Float, nullable=False)
    selling_price = Column(Float, nullable=False)
    
    # Chiqim ustalar uchun bo'lsa bog'lanadi
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    # Operator
    user_id = Column(Integer, ForeignKey("users.telegram_id"), nullable=True)
    # Transfer bo'lgandagina target ombor to'ldiriladi
    target_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    product = relationship("Product", back_populates="transactions")
    warehouse = relationship("Warehouse", foreign_keys=[warehouse_id], back_populates="transactions")
    target_warehouse = relationship("Warehouse", foreign_keys=[target_warehouse_id], back_populates="target_transactions")
    customer = relationship("Customer", back_populates="transactions")
    operator = relationship("User", back_populates="transactions")
