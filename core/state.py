import asyncio

# Global async queue to pass webhook payloads to background workers safely
order_queue = asyncio.Queue()
