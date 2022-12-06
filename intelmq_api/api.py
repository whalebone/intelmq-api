"""HTTP-API backend of IntelMQ-Manager

SPDX-FileCopyrightText: 2020 Intevation GmbH <https://intevation.de>
SPDX-License-Identifier: AGPL-3.0-or-later

Funding: of initial version by SUNET
Author(s):
  * Bernhard Herzog <bernhard.herzog@intevation.de>

This module implements the HTTP part of the API backend of
IntelMQ-Manager. The logic itself is in the runctl & files modules.
"""

import json
import pathlib
import string
import typing

from fastapi import APIRouter, Depends, HTTPException, Response, status
from intelmq.lib import utils  # type: ignore
from pydantic import BaseModel
from typing_extensions import Literal  # Python 3.8+

import intelmq_api.config
import intelmq_api.files as files
import intelmq_api.runctl as runctl
import intelmq_api.session as session

from .dependencies import api_config, cached_response, session_store, token_authorization

api = APIRouter()


Levels = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "ALL"]
Actions = Literal["start", "stop", "restart", "reload", "status"]
Groups = Literal["collectors", "parsers", "experts", "outputs", "botnet"]
BotCmds = Literal["get", "pop", "send", "process"]
Pages = Literal["configs", "management", "monitor", "check", "about", "index"]

ID_CHARS = set(string.ascii_letters + string.digits + "-")


def ID(id: str) -> str:
    if not set(id) < ID_CHARS:
        raise ValueError("Invalid character in {!r}".format(id))
    return id


def runner(config: intelmq_api.config.Config = Depends(api_config)):
    return runctl.RunIntelMQCtl(config.intelmq_ctl_cmd)


def file_access(config: intelmq_api.config.Config = Depends(api_config)):
    return files.FileAccess(config)


cached = Depends(cached_response(max_age=3))
authorized = Depends(token_authorization)


class RunRequest(BaseModel):
    bot: str
    cmd: BotCmds
    show: bool = False
    dry: bool = False
    msg: str = ""


class LoginForm(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    login_token: str
    username: str


@api.get("/api/botnet", dependencies=[authorized])
def botnet(action: Actions, group: typing.Optional[Groups] = None,
           runner: runctl.RunIntelMQCtl = Depends(runner)):
    return runner.botnet(action, group)


@api.get("/api/bot", dependencies=[authorized])
def bot(action: Actions, id: str = Depends(ID), runner: runctl.RunIntelMQCtl = Depends(runner)):
    return runner.bot(action, id)


@api.get("/api/getlog", dependencies=[authorized, cached])
def get_log(lines: int, id: str = Depends(ID), level: Levels = "DEBUG",
            runner: runctl.RunIntelMQCtl = Depends(runner)):
    return runner.log(id, lines, level)


@api.get("/api/queues", dependencies=[authorized, cached])
def queues(runner: runctl.RunIntelMQCtl = Depends(runner)):
    return runner.list("queues")


@api.get("/api/queues-and-status", dependencies=[authorized, cached])
def queues_and_status(runner: runctl.RunIntelMQCtl = Depends(runner)):
    return runner.list("queues-and-status")


@api.get("/api/bots", dependencies=[authorized, cached])
def bots(runner: runctl.RunIntelMQCtl = Depends(runner)):
    return runner.list("bots")


@api.get("/api/version", dependencies=[authorized], response_model=typing.Dict)
def version(runner: runctl.RunIntelMQCtl = Depends(runner)):
    return runner.version()


@api.get("/api/check", dependencies=[authorized])
def check(runner: runctl.RunIntelMQCtl = Depends(runner)):
    return runner.check()


@api.get("/api/clear", dependencies=[authorized])
def clear(id: str = Depends(ID), runner: runctl.RunIntelMQCtl = Depends(runner)):
    return runner.clear(id)


@api.post("/api/run", dependencies=[authorized], response_model=str)
def run(command: RunRequest, runner: runctl.RunIntelMQCtl = Depends(runner)):
    return runner.run(command.bot, command.cmd, command.show, command.dry, command.msg)


@api.get("/api/debug", dependencies=[authorized])
def debug(runner: runctl.RunIntelMQCtl = Depends(runner)):
    return runner.debug()


@api.get("/api/config", dependencies=[authorized])
def config(response: Response, file: str, fetch: bool = False,
           file_access: files.FileAccess = Depends(file_access)):
    result = file_access.load_file_or_directory(file, fetch)
    if result is None:
        return ["Unknown resource"]

    content_type, contents = result
    response.headers["content-type"] = content_type
    return contents


@api.post("/api/login", status_code=status.HTTP_200_OK, response_model=TokenResponse)
def login(login_form: LoginForm, session: session.SessionStore = Depends(session_store)):
    username, password = login_form.username, login_form.password
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session store is disabled by configuration! No login possible and required.",
        )
    else:
        known = session.verify_user(username, password)
        if known is not None:
            token = session.new_session({"username": username})
            return {"login_token": token,
                    "username": username,
                    }
        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Invalid username and/or password.")


@api.get("/api/harmonization", dependencies=[authorized], response_model=typing.Dict)
def get_harmonization(runner: runctl.RunIntelMQCtl = Depends(runner)):
    harmonization = pathlib.Path('/opt/intelmq/etc/harmonization.conf')
    paths = runner.get_paths()
    if 'CONFIG_DIR' in paths:
        harmonization = pathlib.Path(paths['CONFIG_DIR']) / 'harmonization.conf'
    try:
        return json.loads(harmonization.read_text())
    except OSError as e:
        print(f"Could not read {harmonization}: {str(e)}")
        return {}


@api.get("/api/runtime", dependencies=[authorized], response_model=typing.Dict)
def get_runtime():
    return utils.get_runtime()


@api.post("/api/runtime", dependencies=[authorized], response_model=str)
def post_runtime(body: dict):
    try:
        utils.set_runtime(body)
        return "success"
    except Exception as e:
        print(f"Could not write runtime {str(e)}")
        return str(e)


@api.get("/api/positions", dependencies=[authorized], response_model=typing.Dict)
def get_positions(runner: runctl.RunIntelMQCtl = Depends(runner)):
    positions = pathlib.Path('/opt/intelmq/etc/manager/positions.conf')
    paths = runner.get_paths()
    if 'CONFIG_DIR' in paths:
        positions = pathlib.Path(paths['CONFIG_DIR']) / 'manager/positions.conf'
    try:
        return json.loads(positions.read_text())
    except OSError as e:
        print(f"Could not read {positions}: {str(e)}")
        return {}


@api.post("/api/positions", dependencies=[authorized], response_model=str)
def post_positions(body: dict, runner: runctl.RunIntelMQCtl = Depends(runner)):
    positions = pathlib.Path('/opt/intelmq/etc/manager/positions.conf')
    paths = runner.get_paths()
    if 'CONFIG_DIR' in paths:
        positions = pathlib.Path(paths['CONFIG_DIR']) / 'manager/positions.conf'
    try:
        positions.parent.mkdir(exist_ok=True)
        positions.write_text(json.dumps(body, indent=4))
        return "success"
    except OSError as e:
        print(f"Error creating {positions.parent} or writing to {positions}: {str(e)}")
        return str(e)
