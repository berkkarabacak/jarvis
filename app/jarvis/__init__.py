"""Jarvis local colleague agent ==GRoK== — tools, memory, computer-use lite."""

from app.jarvis.agent import JarvisLocalAgent, build_jarvis_agent
from app.jarvis.model_router import ModelRouteChoice, route_model

__all__ = ["JarvisLocalAgent", "build_jarvis_agent", "ModelRouteChoice", "route_model"]
