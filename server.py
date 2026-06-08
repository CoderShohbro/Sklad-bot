import os
import datetime
import asyncio
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend import database, models, config, report_generator
from backend.bot import send_low_stock_warning, send_invoice_notification
from backend.security import verify_telegram_request, get_current_user

app = FastAPI(title="Baraka Sklad — API Server")

# Enable CORS for frontend Web App
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False, # Wildcard origins uchun False bo'lishi lozim (cookielar ishlatilmaydi)
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- PYDANTIC SCHEMAS ---

class CategoryBase(BaseModel):
    name: str

class CategoryCreate(CategoryBase):
    pass

class CategoryOut(CategoryBase):
    id: int
    class Config:
        from_attributes = True

class WarehouseOut(BaseModel):
    id: int
    name: str
    location: Optional[str] = None
    class Config:
        from_attributes = True

class CustomerCreate(BaseModel):
    name: str
    phone: Optional[str] = None

class CustomerOut(BaseModel):
    id: int
    name: str
    phone: Optional[str] = None
    balance: float
    created_at: datetime.datetime
    class Config:
        from_attributes = True

class ProductCreate(BaseModel):
    barcode: str
    name: str
    category_id: int
    cost_price: float = Field(..., gt=0)
    selling_price: float = Field(..., gt=0)
    min_threshold: float = Field(10.0, ge=0)
    warehouse_id: int = 1 # Qaysi omborga boshlang'ich qoldiq qo'shilayotgani
    initial_stock: float = Field(0.0, ge=0)

class ProductStockOut(BaseModel):
    warehouse_id: int
    warehouse_name: str
    quantity: float

class ProductOut(BaseModel):
    id: int
    barcode: str
    name: str
    category_id: int
    category_name: str
    cost_price: float
    selling_price: float
    min_threshold: float
    stocks: List[ProductStockOut]
    created_at: datetime.datetime
    class Config:
        from_attributes = True

class TransactionCreate(BaseModel):
    product_id: int
    warehouse_id: int
    type: str  # Kirim, Chiqim, Transfer, Spisat
    quantity: float = Field(..., gt=0)
    customer_id: Optional[int] = None
    target_warehouse_id: Optional[int] = None  # Faqat Transfer uchun
    user_id: Optional[int] = None  # Telegram user ID

class TransactionOut(BaseModel):
    id: int
    product_name: str
    warehouse_name: str
    type: str
    quantity: float
    price: float
    total_price: float
    customer_name: Optional[str]
    operator_name: Optional[str]
    created_at: datetime.datetime
    class Config:
        from_attributes = True

class DashboardStats(BaseModel):
    kirim_sum: float
    chiqim_sum: float
    net_profit: float
    total_stock_count: float

class ChartDataPoint(BaseModel):
    date: str
    kirim: float
    chiqim: float

class CustomerTransactionOut(BaseModel):
    id: int
    product_name: str
    type: str
    quantity: float
    price: float
    total_price: float
    created_at: datetime.datetime
    class Config:
        from_attributes = True

class TopDebtorOut(BaseModel):
    id: int
    name: str
    balance: float

class CategoryValueOut(BaseModel):
    category_name: str
    total_value: float

class DashboardWidgetsOut(BaseModel):
    top_debtors: List[TopDebtorOut]
    category_shares: List[CategoryValueOut]

class UserCreate(BaseModel):
    telegram_id: int
    username: Optional[str] = None
    full_name: str
    role: str = "Skladchi"

class UserUpdate(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None

class UserOut(BaseModel):
    id: int
    telegram_id: int
    username: Optional[str] = None
    full_name: str
    role: str
    is_active: bool
    created_at: datetime.datetime
    class Config:
        from_attributes = True

# --- API ENDPOINTS ---

@app.get("/api/dashboard", response_model=DashboardStats)
def get_dashboard_stats(db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    """Dashboard uchun umumiy statistikalarni hisoblash (Rollar tekshiruvi bilan)"""
    # Skladchi/Ishchiga moliyaviy ma'lumotlarni ko'rsatmaymiz
    if current_user.role != "Admin":
        total_stock_count = db.query(func.sum(models.Stock.quantity)).scalar() or 0.0
        return {
            "kirim_sum": 0.0,
            "chiqim_sum": 0.0,
            "net_profit": 0.0,
            "total_stock_count": total_stock_count
        }
        
    # Kirim summasini hisoblash
    kirim_q = db.query(func.sum(models.Transaction.quantity * models.Transaction.cost_price))\
        .filter(models.Transaction.type == "Kirim").scalar() or 0.0
        
    # Chiqim summasini hisoblash
    chiqim_q = db.query(func.sum(models.Transaction.quantity * models.Transaction.selling_price))\
        .filter(models.Transaction.type == "Chiqim").scalar() or 0.0

    # Sof foyda = (sotish narxi - tannarxi) * miqdor (chiqim qilingan tovarlar uchun)
    transactions = db.query(models.Transaction).filter(models.Transaction.type == "Chiqim").all()
    net_profit = sum(t.quantity * (t.selling_price - t.cost_price) for t in transactions)
    
    # Skladdagi jami tovarlar soni (miqdori)
    total_stock_count = db.query(func.sum(models.Stock.quantity)).scalar() or 0.0
    
    return {
        "kirim_sum": kirim_q,
        "chiqim_sum": chiqim_q,
        "net_profit": net_profit,
        "total_stock_count": total_stock_count
    }

@app.get("/api/dashboard/chart", response_model=List[ChartDataPoint])
def get_chart_data(db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    """Chart.js uchun oxirgi 7 kunlik aylanma grafigi ma'lumotlari (Skladchi uchun yopiq)"""
    chart_data = []
    
    if current_user.role != "Admin":
        return []
        
    today = datetime.date.today()
    
    for i in range(6, -1, -1):
        day = today - datetime.timedelta(days=i)
        day_start = datetime.datetime.combine(day, datetime.time.min)
        day_end = datetime.datetime.combine(day, datetime.time.max)
        
        # Kirimlar summasi
        k_sum = db.query(func.sum(models.Transaction.quantity * models.Transaction.cost_price))\
            .filter(models.Transaction.type == "Kirim", 
                    models.Transaction.created_at >= day_start, 
                    models.Transaction.created_at <= day_end).scalar() or 0.0
                    
        # Chiqimlar summasi
        c_sum = db.query(func.sum(models.Transaction.quantity * models.Transaction.selling_price))\
            .filter(models.Transaction.type == "Chiqim", 
                    models.Transaction.created_at >= day_start, 
                    models.Transaction.created_at <= day_end).scalar() or 0.0
                    
        chart_data.append({
            "date": day.strftime("%d-%b"),
            "kirim": k_sum,
            "chiqim": c_sum
        })
        
    return chart_data

@app.get("/api/products", response_model=List[ProductOut])
def get_products(q: Optional[str] = None, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    """Barcha mahsulotlar va ularning omborlardagi qoldiqlarini olish (Skladchi uchun tannarx yashiriladi)"""
    query = db.query(models.Product)
    if q:
        # Search by barcode or name
        query = query.filter(
            (models.Product.name.like(f"%{q}%")) | 
            (models.Product.barcode == q)
        )
    products = query.all()
    
    out = []
    for p in products:
        stocks_out = []
        for stock in p.stocks:
            stocks_out.append({
                "warehouse_id": stock.warehouse_id,
                "warehouse_name": stock.warehouse.name,
                "quantity": stock.quantity
            })
            
        # Agar tovar omborda bo'lmasa lekin ro'yxatda bo'lsa, 0 deb qo'shiladi
        all_warehouses = db.query(models.Warehouse).all()
        stock_wh_ids = [s.warehouse_id for s in p.stocks]
        for wh in all_warehouses:
            if wh.id not in stock_wh_ids:
                stocks_out.append({
                    "warehouse_id": wh.id,
                    "warehouse_name": wh.name,
                    "quantity": 0.0
                })
                
        # Cost price is hidden from Skladchi
        cost_price = p.cost_price if current_user.role == "Admin" else 0.0
        
        out.append({
            "id": p.id,
            "barcode": p.barcode,
            "name": p.name,
            "category_id": p.category_id,
            "category_name": p.category.name,
            "cost_price": cost_price,
            "selling_price": p.selling_price,
            "min_threshold": p.min_threshold,
            "stocks": stocks_out,
            "created_at": p.created_at
        })
    return out

@app.post("/api/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(product_in: ProductCreate, db: Session = Depends(database.get_db), tg_check: bool = Depends(verify_telegram_request)):
    """Yangi mahsulot yaratish va boshlang'ich qoldiqni kiritish"""
    # Barcode unique check
    existing = db.query(models.Product).filter_by(barcode=product_in.barcode).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ushbu shtrix-kodli tovar allaqachon mavjud!")
        
    # Check category
    category = db.query(models.Category).get(product_in.category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Kategoriya topilmadi!")

    # Check warehouse
    warehouse = db.query(models.Warehouse).get(product_in.warehouse_id)
    if not warehouse:
        raise HTTPException(status_code=404, detail="Ombor topilmadi!")
        
    # Create product
    new_product = models.Product(
        barcode=product_in.barcode,
        name=product_in.name,
        category_id=product_in.category_id,
        cost_price=product_in.cost_price,
        selling_price=product_in.selling_price,
        min_threshold=product_in.min_threshold
    )
    db.add(new_product)
    db.flush() # ID olish uchun
    
    # Initialize stock
    new_stock = models.Stock(
        product_id=new_product.id,
        warehouse_id=product_in.warehouse_id,
        quantity=product_in.initial_stock
    )
    db.add(new_stock)
    
    # Boshlang'ich kirim tranzaksiyasi
    if product_in.initial_stock > 0:
        new_tx = models.Transaction(
            product_id=new_product.id,
            warehouse_id=product_in.warehouse_id,
            type="Kirim",
            quantity=product_in.initial_stock,
            cost_price=product_in.cost_price,
            selling_price=product_in.selling_price,
            created_at=datetime.datetime.utcnow()
        )
        db.add(new_tx)
        
    db.commit()
    db.refresh(new_product)
    
    # Reshape return structure
    stocks_out = [{
        "warehouse_id": warehouse.id,
        "warehouse_name": warehouse.name,
        "quantity": product_in.initial_stock
    }]
    
    return {
        "id": new_product.id,
        "barcode": new_product.barcode,
        "name": new_product.name,
        "category_id": new_product.category_id,
        "category_name": category.name,
        "cost_price": new_product.cost_price,
        "selling_price": new_product.selling_price,
        "min_threshold": new_product.min_threshold,
        "stocks": stocks_out,
        "created_at": new_product.created_at
    }

@app.get("/api/categories", response_model=List[CategoryOut])
def get_categories(db: Session = Depends(database.get_db)):
    """Kategoriyalarni olish"""
    return db.query(models.Category).all()

@app.post("/api/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(cat: CategoryCreate, db: Session = Depends(database.get_db), tg_check: bool = Depends(verify_telegram_request)):
    """Yangi kategoriya qo'shish"""
    existing = db.query(models.Category).filter_by(name=cat.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Bu kategoriya allaqachon mavjud!")
    new_cat = models.Category(name=cat.name)
    db.add(new_cat)
    db.commit()
    db.refresh(new_cat)
    return new_cat

@app.get("/api/warehouses", response_model=List[WarehouseOut])
def get_warehouses(db: Session = Depends(database.get_db)):
    """Omborlarni olish"""
    return db.query(models.Warehouse).all()

@app.get("/api/customers", response_model=List[CustomerOut])
def get_customers(db: Session = Depends(database.get_db)):
    """Ustalar (Mijozlar) ro'yxatini olish"""
    return db.query(models.Customer).all()

@app.post("/api/customers", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(cust: CustomerCreate, db: Session = Depends(database.get_db), tg_check: bool = Depends(verify_telegram_request)):
    """Yangi mijoz (usta) qo'shish"""
    new_cust = models.Customer(name=cust.name, phone=cust.phone, balance=0.0)
    db.add(new_cust)
    db.commit()
    db.refresh(new_cust)
    return new_cust

@app.post("/api/transactions", status_code=status.HTTP_201_CREATED)
async def create_transaction(tx: TransactionCreate, db: Session = Depends(database.get_db), tg_check: bool = Depends(verify_telegram_request)):
    """Tezkor amallarni amalga oshirish: Kirim, Chiqim, Transfer, Spisat"""
    # Fetch Product and Warehouse
    product = db.query(models.Product).get(tx.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Mahsulot topilmadi!")
        
    warehouse = db.query(models.Warehouse).get(tx.warehouse_id)
    if not warehouse:
        raise HTTPException(status_code=404, detail="Manba ombor topilmadi!")
        
    # Get or create stock record for this warehouse
    stock = db.query(models.Stock).filter_by(product_id=tx.product_id, warehouse_id=tx.warehouse_id).first()
    if not stock:
        stock = models.Stock(product_id=tx.product_id, warehouse_id=tx.warehouse_id, quantity=0.0)
        db.add(stock)

    if tx.type == "Kirim":
        stock.quantity += tx.quantity
        
    elif tx.type == "Chiqim":
        if stock.quantity < tx.quantity:
            raise HTTPException(status_code=400, detail="Omborda ushbu miqdorda tovar yo'q!")
        stock.quantity -= tx.quantity
        
        # Check low stock threshold -> Trigger background notification
        if stock.quantity <= product.min_threshold:
            # Run async bot warning task
            asyncio.create_task(send_low_stock_warning(
                product_name=product.name, 
                current_quantity=stock.quantity, 
                threshold=product.min_threshold,
                warehouse_name=warehouse.name
            ))
            
        # Update customer balance if provided
        if tx.customer_id:
            customer = db.query(models.Customer).get(tx.customer_id)
            if customer:
                total_sale = tx.quantity * product.selling_price
                customer.balance -= total_sale  # Sklad oldidagi qarzi ko'payadi (balansi kamayadi)
                db.flush()
                
                # Send receipt check directly to customer Telegram if they are registered users,
                # or just log it and send to operators
                if tx.user_id:
                    asyncio.create_task(send_invoice_notification(
                        telegram_id=tx.user_id,
                        customer_name=customer.name,
                        product_name=product.name,
                        quantity=tx.quantity,
                        total_price=total_sale,
                        current_balance=customer.balance
                    ))
                    
    elif tx.type == "Transfer":
        if not tx.target_warehouse_id:
            raise HTTPException(status_code=400, detail="Mo'ljaldagi ombor (target_warehouse_id) kiritilmagan!")
            
        target_wh = db.query(models.Warehouse).get(tx.target_warehouse_id)
        if not target_wh:
            raise HTTPException(status_code=404, detail="Qabul qiluvchi ombor topilmadi!")
            
        if stock.quantity < tx.quantity:
            raise HTTPException(status_code=400, detail="Omborda transfer qilish uchun yetarli miqdor yo'q!")
            
        # Decrease source stock
        stock.quantity -= tx.quantity
        
        # Check low stock on source
        if stock.quantity <= product.min_threshold:
            asyncio.create_task(send_low_stock_warning(
                product_name=product.name,
                current_quantity=stock.quantity,
                threshold=product.min_threshold,
                warehouse_name=warehouse.name
            ))
            
        # Increase target stock
        target_stock = db.query(models.Stock).filter_by(product_id=tx.product_id, warehouse_id=tx.target_warehouse_id).first()
        if not target_stock:
            target_stock = models.Stock(product_id=tx.product_id, warehouse_id=tx.target_warehouse_id, quantity=0.0)
            db.add(target_stock)
        target_stock.quantity += tx.quantity
        
    elif tx.type == "Spisat":
        if stock.quantity < tx.quantity:
            raise HTTPException(status_code=400, detail="Omborda spisat qilish uchun yetarli miqdor yo'q!")
        stock.quantity -= tx.quantity
        
        if stock.quantity <= product.min_threshold:
            asyncio.create_task(send_low_stock_warning(
                product_name=product.name,
                current_quantity=stock.quantity,
                threshold=product.min_threshold,
                warehouse_name=warehouse.name
            ))
            
    else:
        raise HTTPException(status_code=400, detail="Noto'g'ri tranzaksiya turi!")

    # Log Transaction
    new_tx = models.Transaction(
        product_id=tx.product_id,
        warehouse_id=tx.warehouse_id,
        type=tx.type,
        quantity=tx.quantity,
        cost_price=product.cost_price,
        selling_price=product.selling_price,
        customer_id=tx.customer_id,
        target_warehouse_id=tx.target_warehouse_id,
        user_id=tx.user_id,
        created_at=datetime.datetime.utcnow()
    )
    db.add(new_tx)
    db.commit()
    return {"status": "success", "message": "Tranzaksiya muvaffaqiyatli yakunlandi"}

@app.get("/api/transactions", response_model=List[TransactionOut])
def get_transactions_history(db: Session = Depends(database.get_db)):
    """Operatsiyalar tarixini olish"""
    transactions = db.query(models.Transaction).order_by(models.Transaction.created_at.desc()).limit(100).all()
    out = []
    for t in transactions:
        operator_name = t.operator.full_name if t.operator else "Tizim"
        customer_name = t.customer.name if t.customer else None
        price = t.selling_price if t.type in ["Chiqim", "Transfer"] else t.cost_price
        total_price = t.quantity * price
        out.append({
            "id": t.id,
            "product_name": t.product.name,
            "warehouse_name": t.warehouse.name,
            "type": t.type,
            "quantity": t.quantity,
            "price": price,
            "total_price": total_price,
            "customer_name": customer_name,
            "operator_name": operator_name,
            "created_at": t.created_at
        })
    return out

@app.post("/api/sync")
async def sync_offline_cache(payload: List[TransactionCreate], db: Session = Depends(database.get_db), tg_check: bool = Depends(verify_telegram_request)):
    """Oflayn rejimda keshda qolib ketgan amallarni tarmoq tiklangach serverga sinxronizatsiya qilish"""
    synced_count = 0
    errors = []
    
    for idx, tx in enumerate(payload):
        try:
            # We recreate the logic manually here to handle multi-tx in single request
            product = db.query(models.Product).get(tx.product_id)
            if not product:
                errors.append(f"Qator {idx}: Mahsulot topilmadi (ID: {tx.product_id})")
                continue
                
            warehouse = db.query(models.Warehouse).get(tx.warehouse_id)
            if not warehouse:
                errors.append(f"Qator {idx}: Ombor topilmadi (ID: {tx.warehouse_id})")
                continue

            stock = db.query(models.Stock).filter_by(product_id=tx.product_id, warehouse_id=tx.warehouse_id).first()
            if not stock:
                stock = models.Stock(product_id=tx.product_id, warehouse_id=tx.warehouse_id, quantity=0.0)
                db.add(stock)
                
            if tx.type == "Kirim":
                stock.quantity += tx.quantity
            elif tx.type == "Chiqim":
                if stock.quantity < tx.quantity:
                    errors.append(f"Qator {idx}: Omborda yetarli tovar yo'q ({product.name})")
                    continue
                stock.quantity -= tx.quantity
                
                # Check alert
                if stock.quantity <= product.min_threshold:
                    asyncio.create_task(send_low_stock_warning(product.name, stock.quantity, product.min_threshold, warehouse.name))
                
                if tx.customer_id:
                    customer = db.query(models.Customer).get(tx.customer_id)
                    if customer:
                        customer.balance -= tx.quantity * product.selling_price
                        db.flush()
                        if tx.user_id:
                            asyncio.create_task(send_invoice_notification(
                                tx.user_id, customer.name, product.name, tx.quantity,
                                tx.quantity * product.selling_price, customer.balance
                            ))
            elif tx.type == "Transfer":
                if not tx.target_warehouse_id:
                    errors.append(f"Qator {idx}: Transfer uchun qabul qiluvchi ombor kiritilmagan")
                    continue
                target_stock = db.query(models.Stock).filter_by(product_id=tx.product_id, warehouse_id=tx.target_warehouse_id).first()
                if not target_stock:
                    target_stock = models.Stock(product_id=tx.product_id, warehouse_id=tx.target_warehouse_id, quantity=0.0)
                    db.add(target_stock)
                
                if stock.quantity < tx.quantity:
                    errors.append(f"Qator {idx}: Transfer uchun yetarli tovar yo'q ({product.name})")
                    continue
                stock.quantity -= tx.quantity
                target_stock.quantity += tx.quantity
                
                if stock.quantity <= product.min_threshold:
                    asyncio.create_task(send_low_stock_warning(product.name, stock.quantity, product.min_threshold, warehouse.name))
            elif tx.type == "Spisat":
                if stock.quantity < tx.quantity:
                    errors.append(f"Qator {idx}: Spisat uchun yetarli tovar yo'q ({product.name})")
                    continue
                stock.quantity -= tx.quantity
                
                if stock.quantity <= product.min_threshold:
                    asyncio.create_task(send_low_stock_warning(product.name, stock.quantity, product.min_threshold, warehouse.name))
                    
            # Log
            new_tx = models.Transaction(
                product_id=tx.product_id,
                warehouse_id=tx.warehouse_id,
                type=tx.type,
                quantity=tx.quantity,
                cost_price=product.cost_price,
                selling_price=product.selling_price,
                customer_id=tx.customer_id,
                target_warehouse_id=tx.target_warehouse_id,
                user_id=tx.user_id,
                created_at=datetime.datetime.utcnow()
            )
            db.add(new_tx)
            synced_count += 1
            
        except Exception as err:
            errors.append(f"Qator {idx} kutilmagan xato: {str(err)}")
            
    db.commit()
    return {
        "status": "success" if not errors else "partial_success",
        "synced_count": synced_count,
        "errors": errors
    }

@app.get("/api/customers/{id}/history", response_model=List[CustomerTransactionOut])
def get_customer_history(id: int, db: Session = Depends(database.get_db)):
    """Mijozning (ustaning) sotib olish tarixi ledgerini olish"""
    transactions = db.query(models.Transaction)\
        .filter(models.Transaction.customer_id == id)\
        .order_by(models.Transaction.created_at.desc()).all()
    
    out = []
    for t in transactions:
        price = t.selling_price
        total_price = t.quantity * price
        out.append({
            "id": t.id,
            "product_name": t.product.name,
            "type": t.type,
            "quantity": t.quantity,
            "price": price,
            "total_price": total_price,
            "created_at": t.created_at
        })
    return out

@app.get("/api/dashboard/widgets", response_model=DashboardWidgetsOut)
def get_dashboard_widgets(db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    """Top qarzdor ustalar va kategoriyalar bo'yicha tovar qiymati ulushi (Adminlar uchun)"""
    if current_user.role != "Admin":
        return {"top_debtors": [], "category_shares": []}
        
    # 1. Top 3 Debtors (balance < 0)
    debtors = db.query(models.Customer)\
        .filter(models.Customer.balance < 0)\
        .order_by(models.Customer.balance).limit(3).all()
    
    top_debtors = [{"id": d.id, "name": d.name, "balance": d.balance} for d in debtors]
    
    # 2. Category Share Calculation
    shares = db.query(
        models.Category.name,
        func.sum(models.Stock.quantity * models.Product.cost_price)
    ).join(models.Product, models.Product.category_id == models.Category.id)\
     .join(models.Stock, models.Stock.product_id == models.Product.id)\
     .group_by(models.Category.name).all()
     
    category_shares = []
    for name, total_val in shares:
        category_shares.append({
            "category_name": name,
            "total_value": total_val or 0.0
        })
        
    return {
        "top_debtors": top_debtors,
        "category_shares": category_shares
    }

# --- PROFILE & USER MANAGEMENT ENDPOINTS ---

@app.get("/api/users/me")
def get_user_me(current_user: models.User = Depends(get_current_user)):
    """Foydalanuvchining o'z profil ma'lumotlarini olish"""
    return {
        "telegram_id": current_user.telegram_id,
        "username": current_user.username,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "is_active": current_user.is_active
    }

@app.get("/api/users", response_model=List[UserOut])
def get_users_list(db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    """Ishchilar ro'yxatini ko'rish (Faqat admin uchun)"""
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Ruxsat etilmadi (Faqat Admin uchun)!")
    return db.query(models.User).all()

@app.post("/api/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_new_user(user_in: UserCreate, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    """Yangi ishchi/admin qo'shish (Faqat admin uchun)"""
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Ruxsat etilmadi (Faqat Admin uchun)!")
        
    existing = db.query(models.User).filter_by(telegram_id=user_in.telegram_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ushbu Telegram ID dagi foydalanuvchi allaqachon mavjud!")
        
    new_user = models.User(
        telegram_id=user_in.telegram_id,
        username=user_in.username,
        full_name=user_in.full_name,
        role=user_in.role,
        is_active=True
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@app.patch("/api/users/{telegram_id}", response_model=UserOut)
def update_user_status(telegram_id: int, user_update: UserUpdate, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    """Ishchining roli yoki faolligini o'zgartirish (Faqat admin uchun)"""
    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Ruxsat etilmadi (Faqat Admin uchun)!")
        
    user = db.query(models.User).filter_by(telegram_id=telegram_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi!")
        
    if user_update.role is not None:
        user.role = user_update.role
    if user_update.is_active is not None:
        user.is_active = user_update.is_active
        
    db.commit()
    db.refresh(user)
    return user

@app.get("/api/export/excel")
async def export_accounting_excel(db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    """Barcha moliyaviy ma'lumotlarni Excel formatida generatsiya qilib, foydalanuvchining Telegramiga yuboradi (WebView yuklash cheklovini aylanib o'tish)"""
    try:
        filepath = f"data/reports/hisobot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        report_generator.generate_accounting_excel(db, filepath)
        
        if os.path.exists(filepath):
            from backend.bot import bot
            from aiogram.types import FSInputFile
            
            file_input = FSInputFile(filepath)
            await bot.send_document(
                chat_id=current_user.telegram_id,
                document=file_input,
                caption=f"📊 **Baraka Sklad** to'liq hisoboti\n📅 Vaqt: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}"
            )
            return {"status": "success", "message": "Excel hisoboti Telegramingizga yuborildi!"}
        else:
            raise HTTPException(status_code=500, detail="Excel fayli generatsiya qilinmadi.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Eksportda xatolik yuz berdi: {str(e)}")

# Mount frontend files at the end of routing table
frontend_dir = os.path.join(config.BASE_DIR, "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
