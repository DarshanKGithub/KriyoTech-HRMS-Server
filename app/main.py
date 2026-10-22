"""Backward-compatible ASGI import path, now served entirely by Django."""
from config.asgi import application

app = application
