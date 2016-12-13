from tornado import web, gen
import json
from notebook.base.handlers import IPythonHandler
from datetime import datetime, timedelta

from ModestMaps.Core import Coordinate
from jinja2 import Template
from .config import KtileConfig, KtileLayerConfig



class KtileHandler(IPythonHandler):
    def initialize(self, ktile_config_manager):
        self.ktile_config_manager = ktile_config_manager
        self.ktile_config_manager.foo = id(ktile_config_manager)

    def post(self, kernel_id):
        self.ktile_config_manager[kernel_id] = KtileConfig()

    def delete(self, kernel_id):
        try:
            del self.ktile_config_manager[kernel_id]
        except KeyError:
            raise web.HTTPError(404, u'Kernel %s not found' % kernel_id)

    def get(self, kernel_id, **kwargs):
        config = self.ktile_config_manager[kernel_id].as_dict()
        try:
            self.finish(config)
        except KeyError:
            raise web.HTTPError(404, u'Kernel %s not found' % kernel_id)


class KtileLayerHandler(IPythonHandler):
    def initialize(self, ktile_config_manager):
        self.ktile_config_manager = ktile_config_manager

    def prepare(self):
        try:
            if self.request.headers["Content-Type"].startswith("application/json"):
                self.request.json = json.loads(self.request.body)
        except Exception:
            self.request.json = None

    def post(self, kernel_id, layer_name, **kwargs):
        try:
            filepath = self.request.json['path']
        except KeyError:
            raise web.HTTPError(500, '"path" not passed')

        try:
            self.ktile_config_manager[kernel_id][layer_name] = \
                KtileLayerConfig(
                    layer_name,
                    provider={
                        "class": "geonotebook.vis.ktile.provider:MapnikPythonProvider",
                        "kwargs": self.request.json
                    })

        except KeyError:
            raise web.HTTPError(404, u'Kernel %s not found' % kernel_id)

        self.finish()

    def get(self, kernel_id, layer_name, **kwargs):
        config = self.ktile_config_manager[kernel_id][layer_name]
        try:
            self.finish(config)
        except KeyError:
            raise web.HTTPError(404, u'Kernel %s not found' % kernel_id)


from concurrent.futures import ThreadPoolExecutor
from tornado import concurrent, ioloop

class KTileAsyncClient(object):
    __instance = None

    def __new__(cls, *args, **kwargs):
        if cls.__instance is None:
            cls.__instance = super(
                KTileAsyncClient, cls).__new__(cls, *args, **kwargs)
        return cls.__instance

    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.io_loop = ioloop.IOLoop.current()

    @concurrent.run_on_executor
    def getTileResponse(self, layer, coord, extension):
        return layer.getTileResponse(coord, extension)

class KtileTileHandler(IPythonHandler):

    def initialize(self, ktile_config_manager):
        self.client = KTileAsyncClient()
        self.ktile_config_manager = ktile_config_manager

    @gen.coroutine
    def get(self, kernel_id, layer_name, x, y, z, extension, **kwargs):

        if self.get_query_argument("debug", default=False):
            from pudb.remote import set_trace; set_trace(term_size=(283, 87))

        config = self.ktile_config_manager[kernel_id].config


        layer = config.layers[layer_name]
        coord = Coordinate(int(y), int(x), int(z))

        status_code, headers, content = yield self.client.getTileResponse(
            layer, coord, extension)


        if layer.max_cache_age is not None:
            expires = datetime.utcnow() + timedelta(
                seconds=layer.max_cache_age)
            headers.setdefault(
                'Expires', expires.strftime('%a %d %b %Y %H:%M:%S GMT'))
            headers.setdefault(
                'Cache-Control', 'public, max-age=%d' % layer.max_cache_age)

        # Force allow cross origin access
        headers["Access-Control-Allow-Origin"] = "*"

        # Fill tornado handler properties with ktile code/header/content
        for k, v in headers.items():
            self.set_header(k, v)

        self.set_status(status_code)

        self.write(content)