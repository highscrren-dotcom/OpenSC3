"""Статус эфира: поддельный obs-websocket v5 на 127.0.0.1 (порт выбирает ОС) и подделка /proc."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from opensc3 import obs
from opensc3.model import Live

try:
    from websockets.exceptions import ConnectionClosed
    from websockets.sync.server import serve
except ImportError:  # без python-websockets ядро работает, а этих тестов просто нет
    serve = None

PASSWORD = "синтетика-123"


class FakeObs:
    """Hello с паролем → Identify → ответы на запросы; всё, что спросили, — в `asked`."""

    def __init__(self, stream=None, record=None, auth=True, fail=None, silent=False):
        self.stream = stream or {"outputActive": False, "outputDuration": 0}
        self.record = record or {"outputActive": False, "outputDuration": 0}
        self.auth, self.fail, self.silent = auth, fail, silent
        self.asked, self.subscriptions = [], []
        self.server = serve(self.handler, "127.0.0.1", 0, subprotocols=["obswebsocket.json"])
        self.port = self.server.socket.getsockname()[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def handler(self, ws):
        try:
            self._talk(ws)
        except ConnectionClosed:
            pass  # клиент ушёл по таймауту — это и проверяем

    def _talk(self, ws):
        hello = {"obsWebSocketVersion": "5.6.0", "rpcVersion": 1}
        if self.auth:
            hello["authentication"] = {"salt": "c29sdA==", "challenge": "Y2hhbGxlbmdl"}
        ws.send(json.dumps({"op": 0, "d": hello}))
        ident = json.loads(ws.recv())
        self.subscriptions.append(ident["d"].get("eventSubscriptions"))
        if self.auth and ident["d"].get("authentication") != obs._auth(PASSWORD, "c29sdA==", "Y2hhbGxlbmdl"):
            ws.close(4009, "Authentication failed")
            return
        ws.send(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}))
        ws.send(json.dumps({"op": 5, "d": {"eventType": "Шум", "eventData": {}}}))  # не заказывали — пропустить
        for raw in ws:
            d = json.loads(raw)["d"]
            self.asked.append(d["requestType"])
            if self.silent:
                continue
            ok = d["requestType"] != self.fail
            data = {"GetStreamStatus": self.stream, "GetRecordStatus": self.record}.get(d["requestType"], {})
            ws.send(json.dumps({"op": 7, "d": {"requestType": d["requestType"], "requestId": d["requestId"],
                                               "requestStatus": {"result": ok, "code": 100 if ok else 500},
                                               "responseData": data}}))

    def close(self):
        self.server.shutdown()
        self.thread.join(2)


@unittest.skipIf(serve is None, "нет python-websockets")
class Live_(unittest.TestCase):
    def run_obs(self, timeout=1.0, password=PASSWORD, **kw):
        srv = FakeObs(**kw)
        self.addCleanup(srv.close)
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.json"
            cfg.write_text(json.dumps({"server_enabled": True, "server_port": srv.port, "auth_required": True,
                                       "server_password": password}))
            with mock.patch.object(obs, "CONFIG", cfg), mock.patch.object(obs, "obs_running", return_value=True):
                res = obs.live_status(timeout=timeout)
        self.assertLessEqual(set(srv.asked), set(obs.REQUESTS))
        self.assertTrue(all(s == 0 for s in srv.subscriptions), "событий не заказываем")
        return res, srv

    def test_off(self):
        (live, since), srv = self.run_obs()
        self.assertEqual((live, since), (Live.OFF, None))
        self.assertEqual(sorted(srv.asked), sorted(obs.REQUESTS))

    def test_stream_on_with_start_time(self):
        with mock.patch.object(obs.time, "time", return_value=10_000.0):
            (live, since), _ = self.run_obs(stream={"outputActive": True, "outputDuration": 90_500})
        self.assertEqual(live, Live.ON)
        self.assertAlmostEqual(since, 10_000.0 - 90.5)

    def test_record_on(self):
        (live, _), _ = self.run_obs(record={"outputActive": True, "outputPaused": True, "outputDuration": 1000})
        self.assertEqual(live, Live.ON)

    def test_wrong_password_unknown(self):
        (live, since), _ = self.run_obs(password="не тот")
        self.assertEqual((live, since), (Live.UNKNOWN, None))

    def test_request_failure_unknown(self):
        (live, _), _ = self.run_obs(fail="GetRecordStatus")
        self.assertEqual(live, Live.UNKNOWN)

    def test_timeout_unknown(self):
        (live, _), _ = self.run_obs(timeout=0.3, silent=True)
        self.assertEqual(live, Live.UNKNOWN)

    def test_no_auth(self):
        (live, _), _ = self.run_obs(auth=False, password="")
        self.assertEqual(live, Live.OFF)


class Process(unittest.TestCase):
    def test_not_running_is_off_without_connecting(self):
        with mock.patch.object(obs, "obs_running", return_value=False), mock.patch.object(obs, "_ask") as ask:
            self.assertEqual(obs.live_status(), (Live.OFF, None))
        ask.assert_not_called()

    def test_running_but_no_server_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.json"
            cfg.write_text(json.dumps({"server_enabled": False, "server_port": 1}))
            with mock.patch.object(obs, "CONFIG", cfg), mock.patch.object(obs, "obs_running", return_value=True):
                self.assertEqual(obs.live_status(), (Live.UNKNOWN, None))
            with mock.patch.object(obs, "CONFIG", Path(d) / "нет.json"), \
                    mock.patch.object(obs, "obs_running", return_value=True):
                self.assertEqual(obs.live_status(), (Live.UNKNOWN, None))

    def test_refused_port_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.json"
            cfg.write_text(json.dumps({"server_enabled": True, "server_port": 9, "server_password": "x"}))
            with mock.patch.object(obs, "CONFIG", cfg), mock.patch.object(obs, "obs_running", return_value=True):
                self.assertEqual(obs.live_status(timeout=0.5), (Live.UNKNOWN, None))

    def test_obs_running_by_comm(self):
        with tempfile.TemporaryDirectory() as d:
            proc = Path(d)
            for pid, comm in (("1", "systemd"), ("42", "obs-browser-pag"), ("self", "obs")):
                (proc / pid).mkdir()
                (proc / pid / "comm").write_text(comm + "\n")
            self.assertFalse(obs.obs_running(proc))
            (proc / "77").mkdir()
            (proc / "77" / "comm").write_text("obs\n")
            self.assertTrue(obs.obs_running(proc))

    def test_interpret(self):
        off = {"outputActive": False, "outputDuration": 0}
        self.assertEqual(obs.interpret({"GetStreamStatus": off, "GetRecordStatus": off}, 50.0), (Live.OFF, None))
        both = {"GetStreamStatus": {"outputActive": True, "outputDuration": 2000},
                "GetRecordStatus": {"outputActive": True, "outputDuration": 7000}}
        self.assertEqual(obs.interpret(both, 50.0), (Live.ON, 43.0))  # с начала самого раннего


if __name__ == "__main__":
    unittest.main()
