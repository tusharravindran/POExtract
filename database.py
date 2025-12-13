"""
Production Database Module - PostgreSQL with SQLAlchemy
Single database with two tables connected by foreign key (EAN)
"""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey, Index, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session, relationship
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager

# Load environment variables from .env file
load_dotenv()

Base = declarative_base()

# ==================== CONFIGURATION ====================
# Load from environment variables (fallback to SQLite for development)
# Support DATABASE_URL (used by Render, Heroku, etc.) or individual components
DATABASE_URL = os.getenv('DATABASE_URL')

if DATABASE_URL:
    # Render/Heroku style: postgres://user:pass@host:port/dbname
    # SQLAlchemy needs postgresql:// (not postgres://)
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    DB_TYPE = 'postgresql'
else:
    # Build from individual components
    DB_TYPE = os.getenv('DB_TYPE', 'sqlite')  # Change to 'postgresql' for production
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = os.getenv('DB_PORT', '5432')
    DB_NAME = os.getenv('DB_NAME', 'poextract_db')
    DB_USER = os.getenv('DB_USER', 'postgres')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    
    # Build connection string
    if DB_TYPE == 'postgresql':
        DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    elif DB_TYPE == 'sqlite':
        # SQLite fallback for development
        DATABASE_URL = "sqlite:///poextract.db"
    else:
        raise ValueError(f"Unsupported DB_TYPE: {DB_TYPE}")

# ==================== ENGINE & SESSION ====================
# Determine DB_TYPE from DATABASE_URL if not explicitly set
if not DATABASE_URL or DATABASE_URL.startswith('sqlite'):
    db_type_for_engine = 'sqlite'
else:
    db_type_for_engine = 'postgresql'

if db_type_for_engine == 'postgresql':
    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=False
    )
else:
    # SQLite doesn't need connection pooling
    engine = create_engine(
        DATABASE_URL,
        echo=False
    )

SessionLocal = scoped_session(sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
))

# ==================== MODELS ====================

class StyleMaster(Base):
    """
    Style Master table - EAN to Style/Buyer mappings
    id is PRIMARY KEY, ean is UNIQUE (used for foreign key relationship)
    """
    __tablename__ = 'style_master'
    
    id = Column(Integer, primary_key=True, autoincrement=True)  # Standard ID as PK
    ean = Column(String, unique=True, nullable=False, index=True)  # EAN is UNIQUE, used for FK
    style_no = Column(String)
    buyer = Column(String)
    
    # Relationship: One style_master can have many po_items
    po_items = relationship("POItem", back_populates="style_master_ref", foreign_keys="POItem.ean")
    
    def to_dict(self):
        return {
            'id': self.id,
            'ean': self.ean,
            'style_no': self.style_no,
            'buyer': self.buyer
        }


class POItem(Base):
    """
    Purchase Order Items table
    Connected to style_master via EAN foreign key
    """
    __tablename__ = 'po_items'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Foreign Key to style_master (EAN links to style_master.ean)
    ean = Column(String, ForeignKey('style_master.ean', ondelete='SET NULL'), nullable=True, index=True)
    
    # Relationship: Many po_items belong to one style_master
    style_master_ref = relationship("StyleMaster", back_populates="po_items", foreign_keys=[ean])
    
    # File & PO Information
    filename = Column(String)
    po_number = Column(String, index=True)
    po_date = Column(String)
    
    # Product Information (can be populated from style_master via JOIN)
    style_no = Column(String, index=True)  # Denormalized for performance
    ocn = Column(String)
    buyer = Column(String, index=True)  # Denormalized for performance
    description = Column(String)
    
    # Delivery Information
    delivery_date = Column(String, index=True)
    delivery_month = Column(String)
    location = Column(String)
    
    # Quantity Information
    caselot = Column(Integer)
    quantity = Column(Integer)
    no_of_boxes = Column(Integer)
    
    # Factory Information
    factory = Column(String)
    ex_factory_date = Column(String, index=True)
    factory_remarks = Column(String)
    
    # Dispatch Information
    dispatched_box = Column(Integer, default=0)
    dispatched_qty = Column(Integer, default=0)
    balance = Column(Integer, default=0)
    status = Column(String, default='Pending', index=True)
    dispatch_date = Column(String)
    transporter = Column(String)
    
    # GRN Information
    grn_date = Column(String)
    grn_status = Column(String)
    
    # Metadata
    is_revised = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    
    # Composite indexes for performance
    __table_args__ = (
        Index('idx_po_ean', 'po_number', 'ean'),
        Index('idx_status_exfactory', 'status', 'ex_factory_date'),
        Index('idx_po_number_ean', 'po_number', 'ean'),  # For duplicate prevention
    )
    
    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'filename': self.filename,
            'po_number': self.po_number,
            'po_date': self.po_date,
            'style_no': self.style_no,
            'ocn': self.ocn,
            'buyer': self.buyer,
            'delivery_date': self.delivery_date,
            'delivery_month': self.delivery_month,
            'location': self.location,
            'ean': self.ean,
            'description': self.description,
            'caselot': self.caselot,
            'quantity': self.quantity,
            'no_of_boxes': self.no_of_boxes,
            'factory': self.factory,
            'ex_factory_date': self.ex_factory_date,
            'factory_remarks': self.factory_remarks,
            'dispatched_box': self.dispatched_box,
            'dispatched_qty': self.dispatched_qty,
            'balance': self.balance,
            'status': self.status,
            'dispatch_date': self.dispatch_date,
            'transporter': self.transporter,
            'grn_date': self.grn_date,
            'grn_status': self.grn_status,
            'is_revised': self.is_revised,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# ==================== HELPER FUNCTIONS ====================

@contextmanager
def get_db_session():
    """Context manager for database sessions with automatic cleanup"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db():
    """Get database session (for Flask integration)"""
    return SessionLocal()


# ==================== BACKWARD COMPATIBILITY ====================
# These functions maintain compatibility with existing app.py code

def get_po_db_connection():
    """
    Backward compatibility function.
    Returns a session instead of raw connection.
    """
    return get_db()


def get_master_db_connection():
    """
    Backward compatibility function.
    Returns a session instead of raw connection.
    Same as get_po_db_connection() since we use one database now.
    """
    return get_db()


def get_style_and_buyer_from_db(ean: str):
    """
    Returns (style_no, buyer) from style_master for a given EAN.
    Uses JOIN query for efficiency.
    """
    with get_db_session() as session:
        style = session.query(StyleMaster).filter_by(ean=ean).first()
        if style:
            return (style.style_no or "", style.buyer or "")
        return "", ""


def initialize_db():
    """Create all tables if they don't exist"""
    Base.metadata.create_all(bind=engine)
    if DATABASE_URL and not DATABASE_URL.startswith('sqlite'):
        # PostgreSQL (from DATABASE_URL or individual components)
        print(f"✓ Database initialized: PostgreSQL")
    else:
        print(f"✓ Database initialized: SQLite (fallback)")


# ==================== EXAMPLE USAGE ====================
if __name__ == "__main__":
    # Initialize database
    initialize_db()
    print("\n✓ Tables created:")
    print("  - style_master: id (PRIMARY KEY), ean (UNIQUE)")
    print("  - po_items: id (PRIMARY KEY), ean (FOREIGN KEY -> style_master.ean)")
    print("\n✓ Foreign key relationship established:")
    print("  po_items.ean -> style_master.ean (EAN links the tables)")
