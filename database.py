from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from backend.config import DATABASE_URL
import datetime

# Create SQLite engine
engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False}  # Needed for SQLite in multi-threaded environments like FastAPI
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# DB dependency for FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Database jadvallarini yaratadi va boshlang'ich ma'lumotlar bilan to'ldiradi (seed data)"""
    from backend import models  # Import models to register them
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # 1. Default Omboblar (Warehouses)
        if db.query(models.Warehouse).count() == 0:
            w1 = models.Warehouse(name="Asosiy Ombor (Markaz)", location="Toshkent sh., Chilonzor")
            w2 = models.Warehouse(name="Yunusobod Filiali", location="Toshkent sh., Yunusobod")
            db.add_all([w1, w2])
            db.commit()

        # 2. Default Kategoriyalar (Categories)
        if db.query(models.Category).count() == 0:
            c1 = models.Category(name="Quruq qorishmalar (Sement)")
            c2 = models.Category(name="Metallurgiya (Armatura)")
            c3 = models.Category(name="G'isht va Bloklar")
            c4 = models.Category(name="Bo'yoq va Suvoqlar")
            db.add_all([c1, c2, c3, c4])
            db.commit()

        # 3. Default Foydalanuvchilar (Users)
        if db.query(models.User).count() == 0:
            # Haqiqiy admin foydalanuvchi sozlandi
            u1 = models.User(
                telegram_id=641993778,
                username="admin_baraka",
                full_name="Loyiha Egasi (Admin)",
                role="Admin",
                is_active=True
            )
            u2 = models.User(
                telegram_id=88888888,
                username="skladchi_vali",
                full_name="Valisher Skladchi",
                role="Skladchi",
                is_active=True
            )
            db.add_all([u1, u2])
            db.commit()

        # 4. Default Ustalar (Customers)
        if db.query(models.Customer).count() == 0:
            cust1 = models.Customer(name="Usta Baxtiyor", phone="+998901234567", balance=-1200000.0) # - qarzdorlik
            cust2 = models.Customer(name="Usta Olimjon", phone="+998939998877", balance=450000.0) # + oldindan to'lov
            cust3 = models.Customer(name="Usta Farrux", phone="+998944561223", balance=0.0)
            db.add_all([cust1, cust2, cust3])
            db.commit()

        # 5. Default Mahsulotlar (Products)
        if db.query(models.Product).count() == 0:
            # Get category IDs
            cat_sement = db.query(models.Category).filter_by(name="Quruq qorishmalar (Sement)").first().id
            cat_armatura = db.query(models.Category).filter_by(name="Metallurgiya (Armatura)").first().id
            cat_gisht = db.query(models.Category).filter_by(name="G'isht va Bloklar").first().id
            
            p1 = models.Product(
                barcode="4601234567890",
                name="Sement M-500 (Qop 50kg)",
                category_id=cat_sement,
                cost_price=65000.0,
                selling_price=78000.0,
                min_threshold=20.0
            )
            p2 = models.Product(
                barcode="4601234567891",
                name="Armatura D-12 (Metr)",
                category_id=cat_armatura,
                cost_price=9500.0,
                selling_price=12000.0,
                min_threshold=100.0
            )
            p3 = models.Product(
                barcode="4601234567892",
                name="Pishgan G'isht (Dona)",
                category_id=cat_gisht,
                cost_price=1200.0,
                selling_price=1600.0,
                min_threshold=1000.0
            )
            p4 = models.Product(
                barcode="4601234567893",
                name="Sement M-400 (Qop 50kg)",
                category_id=cat_sement,
                cost_price=55000.0,
                selling_price=66000.0,
                min_threshold=50.0
            )
            db.add_all([p1, p2, p3, p4])
            db.commit()

            # 6. Default Stock (Sklad qoldiqlari)
            w1_id = db.query(models.Warehouse).first().id
            w2_id = db.query(models.Warehouse).offset(1).first().id

            # Add stocks
            s1 = models.Stock(product_id=p1.id, warehouse_id=w1_id, quantity=150.0) # Sement M500 in W1
            s2 = models.Stock(product_id=p1.id, warehouse_id=w2_id, quantity=5.0)   # Sement M500 in W2 (Kam qoldi! < 20)
            s3 = models.Stock(product_id=p2.id, warehouse_id=w1_id, quantity=1500.0)
            s4 = models.Stock(product_id=p3.id, warehouse_id=w1_id, quantity=800.0) # G'isht in W1 (Kam qoldi! < 1000)
            s5 = models.Stock(product_id=p4.id, warehouse_id=w1_id, quantity=60.0)
            
            db.add_all([s1, s2, s3, s4, s5])
            db.commit()

            # 7. Default Transactions (Kirim-chiqim tarixi)
            # Add some history to render chart
            today = datetime.datetime.now()
            t1 = models.Transaction(
                product_id=p1.id, warehouse_id=w1_id, type="Kirim", quantity=200.0,
                cost_price=65000.0, selling_price=78000.0, user_id=99999999,
                created_at=today - datetime.timedelta(days=2)
            )
            t2 = models.Transaction(
                product_id=p1.id, warehouse_id=w1_id, type="Chiqim", quantity=50.0,
                cost_price=65000.0, selling_price=78000.0, user_id=99999999,
                customer_id=cust1.id,
                created_at=today - datetime.timedelta(days=1)
            )
            t3 = models.Transaction(
                product_id=p2.id, warehouse_id=w1_id, type="Kirim", quantity=2000.0,
                cost_price=9500.0, selling_price=12000.0, user_id=88888888,
                created_at=today - datetime.timedelta(days=1)
            )
            t4 = models.Transaction(
                product_id=p3.id, warehouse_id=w1_id, type="Chiqim", quantity=200.0,
                cost_price=1200.0, selling_price=1600.0, user_id=99999999,
                customer_id=cust2.id,
                created_at=today
            )
            db.add_all([t1, t2, t3, t4])
            db.commit()

    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
    finally:
        db.close()
