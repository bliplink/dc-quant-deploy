#!/usr/bin/env python3
"""T330 fresh Demo ONLY: restore existing Robot runtime and manager identities.

Read the *deployed* RobotSvr environment in-process (no credential printing).
Write only PLATFORM users/API identity into the brand-new T330 MySQL instance.
Never reset password, key, WAL, or T318 signed Common evidence.
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def container_env(name):
    result = subprocess.run(
        ["docker", "inspect", name, "--format", "{{json .Config.Env}}"],
        check=True, text=True, capture_output=True,
    )
    return dict(x.split("=", 1) for x in json.loads(result.stdout) if "=" in x)


def deployed_admin_env():
    cmd = ("set -a; . .env.prod; set +a; "
           "python3 -c 'import os,json;"
           "print(json.dumps({k:os.environ.get(k,\"\") for k in "
           "(\"PLATFORM_ADMIN_USERNAME\",\"PLATFORM_ADMIN_PASSWORD\")}))'")
    result = subprocess.run(["bash", "-c", cmd], cwd=ROOT,
                            check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


def valid_user(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.@-]{3,45}", value):
        raise ValueError("invalid configured user identifier")
    return value


def password_hash(value):
    if not isinstance(value, str) or len(value) < 8:
        raise ValueError("missing configured password")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9]{32,64}", value):
        raise ValueError("existing runtime key is missing or invalid")
    return value


def main():
    mysql = container_env("dc-saas-mysql")
    robot = container_env("dc-saas-robotsvr")
    admin = deployed_admin_env()
    # Prevent accidentally provisioning an old/MySQL production root.
    mounts = json.loads(subprocess.run(
        ["docker", "inspect", "dc-saas-mysql", "--format", "{{json .Mounts}}"],
        check=True, capture_output=True, text=True,
    ).stdout)
    root = next((m.get("Source") for m in mounts if m.get("Destination") == "/var/lib/mysql"), "")
    if not root.endswith("/data/t330-fresh-mysql"):
        raise RuntimeError("T330-only isolated MySQL data root required")
    platform_user = valid_user(admin["PLATFORM_ADMIN_USERNAME"])
    gateway_user = valid_user(robot["ROBOT_GATEWAY_USER"])
    inputs = [
        (platform_user, password_hash(admin["PLATFORM_ADMIN_PASSWORD"]), "Platform Administrator"),
        (valid_user(robot["ROBOT_RUNTIME_USER_ID"]),
         password_hash(robot["ROBOT_RUNTIME_API_SECRET"]), "Robot Runtime"),
    ]
    if gateway_user != platform_user:
        inputs.append((gateway_user, password_hash(robot["ROBOT_GATEWAY_PASSWORD"]), "Robot Gateway Manager"))
    if len({x[0] for x in inputs}) != len(inputs):
        raise ValueError("conflicting Robot runtime identity")
    location = robot["ROBOT_RUNTIME_LOCATION"]
    if location != "PLATFORM":
        raise ValueError("Robot runtime identity must be in PLATFORM")
    robot_key = key(robot["ROBOT_RUNTIME_API_KEY"])
    robot_secret = key(robot["ROBOT_RUNTIME_API_SECRET"])
    users = []
    for user, digest, display in inputs:
        users.append(
            "('%s','%s','%s','%s','1','1','T330 fresh Demo service identity',"
            "NOW(3),NOW(3),'0','0','0','T330','PLATFORM')" %
            (user, user, display, digest))
    sql = (
        "START TRANSACTION;\n"
        "INSERT INTO dc_users(user_id,user_name,name,password,user_type,enable,remark,"
        "create_time,update_time,enable_trade,enable_cash_in,enable_cash_out,close_by,location)"
        " VALUES\n" + ",\n".join(users) +
        " ON DUPLICATE KEY UPDATE password=VALUES(password),enable='1',"
        "update_time=NOW(3),close_by='T330';\n"
        "INSERT INTO dc_users_api(user_id,type,api_key,secret_key,enable,create_time,"
        "update_time,close_by,inf1,location) VALUES"
        "('%s','ROBOT_RUNTIME','%s','%s','1',DATE_FORMAT(NOW(3),'%%Y-%%m-%%d %%H:%%i:%%s.%%f'),"
        "DATE_FORMAT(NOW(3),'%%Y-%%m-%%d %%H:%%i:%%s.%%f'),"
        "'T330','GW-only Robot runtime','PLATFORM')"
        " ON DUPLICATE KEY UPDATE secret_key=VALUES(secret_key),enable='1',"
        "update_time=VALUES(update_time),close_by='T330',location='PLATFORM';\n"
        "COMMIT;\n" % (robot["ROBOT_RUNTIME_USER_ID"], robot_key, robot_secret)
    )
    if not mysql.get("MYSQL_ROOT_PASSWORD"):
        raise ValueError("new MySQL root password not configured")
    result = subprocess.run(
        ["docker", "exec", "-i", "-e", "MYSQL_PWD=" + mysql["MYSQL_ROOT_PASSWORD"],
         "dc-saas-mysql", "mysql", "-uroot", "dc"],
        input=sql, capture_output=True, text=True,
    )
    if result.returncode:
        raise RuntimeError("T330 Robot identity DB initialization failed: " +
                           result.stderr[-700:])
    print("T330_FRESH_PLATFORM_AND_ROBOT_IDENTITY_PASS users=%d runtimeApiKey=existing "
          "credentialsPrinted=false signedCommonUntouched=true" % len(inputs))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("T330_SERVICE_IDENTITY_NO_GO:", str(exc), file=sys.stderr)
        sys.exit(2)
