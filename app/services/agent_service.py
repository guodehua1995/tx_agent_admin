"""
Agent 服务层

供 API 层调用的服务
"""

from app.agents.executor import agent_executor


class AgentService:
    """Agent 服务"""

    @staticmethod
    async def run_agent(agent_name: str, input_data: dict, **kwargs):
        """运行指定 Agent"""
        return await agent_executor.execute(agent_name, input_data, **kwargs)

    @staticmethod
    def list_available_agents():
        """列出可用 Agent"""
        # 导入所有 Agent 以触发注册
        from app.agents.agents import DocToMarkdownAgent
        from app.agents.registry import AgentRegistry

        agents = AgentRegistry.list_agents()
        return [
            {"name": name, "description": cls.description, "version": cls.version}
            for name, cls in agents.items()
        ]


agent_service = AgentService()
