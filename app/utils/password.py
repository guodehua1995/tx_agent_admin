"""密码工具模块

使用 argon2-cffi 替代 passlib 进行密码哈希和验证
"""

import secrets
import string

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# 创建 PasswordHasher 实例
ph = PasswordHasher()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码
    
    Args:
        plain_password: 明文密码
        hashed_password: 哈希后的密码
        
    Returns:
        验证成功返回 True，否则返回 False
    """
    try:
        ph.verify(hashed_password, plain_password)
        return True
    except VerifyMismatchError:
        return False


def get_password_hash(password: str) -> str:
    """获取密码哈希
    
    Args:
        password: 明文密码
        
    Returns:
        哈希后的密码字符串
    """
    return ph.hash(password)


def generate_password(length: int = 12) -> str:
    """生成随机密码
    
    Args:
        length: 密码长度，默认 12 位
        
    Returns:
        随机生成的密码字符串
    """
    alphabet = string.ascii_letters + string.digits + string.punctuation
    return ''.join(secrets.choice(alphabet) for _ in range(length))
