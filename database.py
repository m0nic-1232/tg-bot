from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

# Укажите URL вашей базы данных. SQLite - хороший выбор для простых проектов.
DATABASE_URL = "sqlite:///users.db"  # или "postgresql://user:password@host:port/database_name"

# Создаем движок SQLAlchemy, который управляет подключением к базе данных.
engine = create_engine(DATABASE_URL)

#  Base - это базовый класс для декларативного отображения.
Base = declarative_base()

# Определяем класс User, представляющий таблицу "users" в базе данных.
class User(Base):
    __tablename__ = "users"  # Имя таблицы в базе данных

    # Определение столбцов таблицы:
    id = Column(Integer, primary_key=True)  # Первичный ключ, автоматически увеличивается.
    telegram_id = Column(Integer, unique=True)  # Уникальный идентификатор пользователя в Telegram.
    name = Column(String)  # Имя пользователя.
    age = Column(Integer)  # Возраст пользователя.
    city = Column(String)  # Город пользователя.
    description = Column(String)  # Информация о пользователе (о себе).
    looking_for = Column(String)  # Информация о том, кого ищет пользователь.
    is_searching = Column(Boolean, default=False)  # Флаг, указывающий, находится ли пользователь в активном поиске.
    username = Column(String, nullable=True) # Добавлено поле username
    likes = relationship("Like", back_populates="user") # Связь с таблицей лайков
    notifications = relationship("Notification", back_populates="user") # Связь с уведомлениями

class Like(Base):
    __tablename__ = "likes"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id")) # ID пользователя, который поставил лайк
    liked_user_id = Column(Integer) # ID пользователя, которому поставили лайк
    is_like = Column(Boolean) # True - лайк, False - дизлайк
    timestamp = Column(DateTime, default=datetime.utcnow) # Добавим время лайка

    user = relationship("User", back_populates="likes")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    message = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)
    is_read = Column(Boolean, default=False)

    user = relationship("User", back_populates="notifications")

# Создаем все таблицы, определенные в метаданных Base, в базе данных, связанной с engine.
Base.metadata.create_all(engine)

# Создаем класс Session, который используется для взаимодействия с базой данных.
# Session предоставляет интерфейс для выполнения операций CRUD (Create, Read, Update, Delete).
Session = sessionmaker(bind=engine)

# Пример использования:
if __name__ == '__main__':
    # Создаем сессию
    session = Session()

    # Проверяем, существует ли пользователь с telegram_id=12345
    existing_user = session.query(User).filter_by(telegram_id=12345).first()

    if not existing_user:  # Если пользователя не существует
        # Пример: Добавление нового пользователя
        new_user = User(telegram_id=12345, name="John Doe", age=30, city="New York", description="Friendly guy", looking_for="Someone nice", is_searching=True)
        session.add(new_user)
        session.commit() # Сохраняем изменения в базе данных
        print("Пользователь John Doe успешно добавлен.")
    else:
        print("Пользователь с telegram_id=12345 уже существует!")

    # Пример: Поиск пользователя по telegram_id
    found_user = session.query(User).filter_by(telegram_id=12345).first()
    if found_user:
        print(f"Found user: {found_user.name}, {found_user.age}, {found_user.city}")

    # Пример: Изменение данных пользователя
    if found_user:
        found_user.age = 31
        session.commit()
        print(f"Updated user age to: {found_user.age}")

    # Закрываем сессию (важно для освобождения ресурсов)
    session.close()
