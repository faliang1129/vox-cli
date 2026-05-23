"""安全策略拦截异常"""

class PolicyException(Exception):
    """路径围栏、命令围栏等安全策略拦截时抛出"""
    pass
