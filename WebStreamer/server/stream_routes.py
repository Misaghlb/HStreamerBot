# Code optimized by fyaz05
# Code from Eyaadh


import time
import math
import logging
import mimetypes
import traceback
from aiohttp import web
from aiohttp.http_exceptions import BadStatusLine
from WebStreamer.bot import multi_clients, work_loads, StreamBot
from WebStreamer.vars import Var
from WebStreamer.server.exceptions import FIleNotFound, InvalidHash
from WebStreamer import utils, StartTime, __version__
from WebStreamer.utils.render_template import render_page
import aiohttp
from urllib.parse import unquote
import asyncio
import os

routes = web.RouteTableDef()

@routes.get("/", allow_head=True)
async def root_route_handler(_):
    return web.Response(text="<html><body><h1>Hello, World!</h1></body></html>", content_type='text/html')

@routes.get("/stats", allow_head=True)
async def root_route_handler(_):
    """Handler for status endpoint."""
    return web.json_response({
        "server_status": "running",
        "uptime": utils.get_readable_time(time.time() - StartTime),
        "telegram_bot": "@" + StreamBot.username,
        "connected_bots": len(multi_clients),
        "loads": {
            f"bot{c+1}": l for c, (_, l) in enumerate(
                sorted(work_loads.items(), key=lambda x: x[1], reverse=True)
            )
        },
        "version": __version__,
    })

@routes.get("/watch/{path}", allow_head=True)
async def watch_handler(request: web.Request):
    """Handler for watch endpoint."""
    try:
        path = request.match_info["path"]
        return web.Response(text=await render_page(path), content_type='text/html')
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message)
    except (AttributeError, BadStatusLine, ConnectionResetError):
        pass
    except Exception as e:
        logging.critical(e)
        logging.debug(traceback.format_exc())
        raise web.HTTPInternalServerError(text=str(e))

@routes.get("/dl/{path}", allow_head=True)
async def download_handler(request: web.Request):
    """Handler for download endpoint."""
    try:
        path = request.match_info["path"]
        return await media_streamer(request, path)
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message)
    except (AttributeError, BadStatusLine, ConnectionResetError):
        pass
    except Exception as e:
        logging.critical(e)
        logging.debug(traceback.format_exc())
        raise web.HTTPInternalServerError(text=str(e))

@routes.get("/stream/{path}", allow_head=True)
async def stream_handler(request: web.Request):
    """Handler for stream endpoint."""
    try:
        path = request.match_info["path"]
        return await media_streamer(request, path)
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message)
    except (AttributeError, BadStatusLine, ConnectionResetError):
        pass
    except Exception as e:
        logging.critical(e)
        logging.debug(traceback.format_exc())
        raise web.HTTPInternalServerError(text=str(e))

class_cache = {}

async def media_streamer(request: web.Request, db_id: str):
    """Stream media file."""

    range_header = request.headers.get("Range")
    client_index = min(work_loads, key=work_loads.get)
    fastest_client = multi_clients[client_index]

    if Var.MULTI_CLIENT:
        logging.info(f"Client {client_index} is now serving {request.headers.get('X-FORWARDED-FOR', request.remote)}")

    if fastest_client in class_cache:
        tg_connect = class_cache[fastest_client]
        logging.debug(f"Using cached ByteStreamer object for client {client_index}")
    else:
        logging.debug(f"Creating new ByteStreamer object for client {client_index}")
        tg_connect = utils.ByteStreamer(fastest_client)
        class_cache[fastest_client] = tg_connect

    logging.debug("before calling get_file_properties")
    file_id = await tg_connect.get_file_properties(db_id, multi_clients)
    logging.debug("after calling get_file_properties")

    file_size = file_id.file_size
    from_bytes, until_bytes = parse_range_header(range_header, file_size)

    if (until_bytes >= file_size) or (from_bytes < 0) or (until_bytes < from_bytes):
        return web.Response(
            status=416,
            body="416: Range not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    chunk_size = 1024 * 1024
    until_bytes = min(until_bytes, file_size - 1)
    offset = from_bytes - (from_bytes % chunk_size)
    first_part_cut = from_bytes - offset
    last_part_cut = until_bytes % chunk_size + 1
    req_length = until_bytes - from_bytes + 1
    part_count = math.ceil((until_bytes + 1) / chunk_size) - math.floor(offset / chunk_size)
    
    body = tg_connect.yield_file(file_id, client_index, offset, first_part_cut, last_part_cut, part_count, chunk_size)

    mime_type = file_id.mime_type or mimetypes.guess_type(utils.get_name(file_id))[0] or "application/octet-stream"
    disposition = "attachment" if "application/" in mime_type or "text/" in mime_type else "inline"

    return web.Response(
        status=206 if range_header else 200,
        body=body,
        headers={
            "Content-Type": mime_type,
            "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
            "Content-Length": str(req_length),
            "Content-Disposition": f'{disposition}; filename="{utils.get_name(file_id)}"',
            "Accept-Ranges": "bytes",
        },
    )

def parse_range_header(header, file_size):
    """Parse Range header and return tuple of (from_bytes, until_bytes)."""
    from_bytes, until_bytes = 0, file_size - 1
    if header:
        range_parts = header.replace("bytes=", "").split("-")
        if range_parts[0]:
            from_bytes = int(range_parts[0])
        if range_parts[1]:
            until_bytes = int(range_parts[1]) if range_parts[1] else file_size - 1
    return from_bytes, until_bytes


# URL
# Increase chunk size for faster downloads
CHUNK_SIZE = 1024 * 1024  # 1MB

# Create a simple cache for file metadata
metadata_cache = {}
CACHE_TTL = 3600  # Cache for 1 hour

# Create a function to get or create the connection pool
async def get_connector():
    if not hasattr(get_connector, 'connector'):
        get_connector.connector = aiohttp.TCPConnector(limit=100)  # Adjust the limit as needed
    return get_connector.connector

@routes.get("/dllink", allow_head=True)
async def download_handler2(request: web.Request):
    """Handler for download endpoint."""
    try:
        url = request.query.get("url")
        if not url:
            raise web.HTTPBadRequest(text="Missing 'url' query parameter")
        url = unquote(url)  # Decode the URL
        return await media_streamer2(request, url)
    except aiohttp.ClientError as e:
        raise web.HTTPBadGateway(text=str(e))
    except Exception as e:
        logging.critical(e)
        logging.debug(traceback.format_exc())
        raise web.HTTPInternalServerError(text=str(e))

async def get_file_metadata(session, url):
    """Get file metadata and cache it."""
    current_time = time.time()
    if url in metadata_cache:
        cached_data, timestamp = metadata_cache[url]
        if current_time - timestamp < CACHE_TTL:
            return cached_data

    async with session.head(url) as response:
        if response.status != 200:
            raise web.HTTPBadGateway(text=f"Failed to fetch URL: HTTP {response.status}")
        file_size = int(response.headers.get("Content-Length", 0))
        mime_type = response.headers.get("Content-Type") or mimetypes.guess_type(url)[0] or "application/octet-stream"
    
    metadata = {"file_size": file_size, "mime_type": mime_type}
    metadata_cache[url] = (metadata, current_time)
    return metadata

async def media_streamer2(request: web.Request, url: str):
    """Stream media file from URL."""
    range_header = request.headers.get("Range")
    
    connector = await get_connector()
    async with aiohttp.ClientSession(connector=connector) as session:
        metadata = await get_file_metadata(session, url)
        file_size = metadata["file_size"]
        mime_type = metadata["mime_type"]

    from_bytes, until_bytes = parse_range_header(range_header, file_size)
    if (until_bytes >= file_size) or (from_bytes < 0) or (until_bytes < from_bytes):
        return web.Response(
            status=416,
            body="416: Range not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    req_length = until_bytes - from_bytes + 1

    async def body():
        connector = await get_connector()
        async with aiohttp.ClientSession(connector=connector) as session:
            headers = {"Range": f"bytes={from_bytes}-{until_bytes}"}
            async with session.get(url, headers=headers) as response:
                while True:
                    chunk = await response.content.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    yield chunk

    disposition = "attachment" if "application/" in mime_type or "text/" in mime_type else "inline"
    filename = os.path.basename(url)

    return web.Response(
        status=206 if range_header else 200,
        body=body(),
        headers={
            "Content-Type": mime_type,
            "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
            "Content-Length": str(req_length),
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Accept-Ranges": "bytes",
        },
    )

def parse_range_header(header, file_size):
    """Parse Range header and return tuple of (from_bytes, until_bytes)."""
    from_bytes, until_bytes = 0, file_size - 1
    if header:
        range_parts = header.replace("bytes=", "").split("-")
        if range_parts[0]:
            from_bytes = int(range_parts[0])
        if range_parts[1]:
            until_bytes = int(range_parts[1]) if range_parts[1] else file_size - 1
    return from_bytes, until_bytes

