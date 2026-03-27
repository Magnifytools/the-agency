import urllib.request
import urllib.error
import urllib.parse
import json

AGENCY_BASE = "http://localhost:8004/api"

def print_result(app, case, result, evidence="", notes=""):
    print(json.dumps({
        "app": app,
        "case": case,
        "result": result,
        "evidence": evidence.replace("\n", " "),
        "notes": notes
    }))

def mk_request(method, url, data=None, headers=None):
    if headers is None:
        headers = {}
    if data is not None and not isinstance(data, bytes):
        data = bytes(json.dumps(data), encoding='utf-8')
        if not 'Content-Type' in headers:
            headers['Content-Type'] = 'application/json'
    
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, response.read().decode(), response.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), e.headers
    except urllib.error.URLError as e:
        return 0, str(e), {}

def test_agency():
    # Smoke
    status, body, headers = mk_request("GET", f"{AGENCY_BASE}/health")
    print_result("Agency", "/api/health", "PASS" if status == 200 else "FAIL", f"Status: {status}", "")

    status, body, headers = mk_request("GET", f"{AGENCY_BASE}/does-not-exist")
    if status == 404 and 'application/json' in headers.get('Content-Type', ''):
        print_result("Agency", "/api/does-not-exist", "PASS", "404 JSON")
    else:
        print_result("Agency", "/api/does-not-exist", "FAIL", f"Status: {status}, Type: {headers.get('Content-Type', '')}")

    # Auth Login Invalid
    status, body, headers = mk_request("POST", f"{AGENCY_BASE}/auth/login", data={"email": "david@magnify.ing", "password": "wrong"})
    if status in [401]:
        print_result("Agency", "Login inválido", "PASS", f"Status: {status}")
    else:
        print_result("Agency", "Login inválido", "FAIL", f"Status: {status} body: {body[:50]}")

    # Auth Login Valid Admin
    status, body, headers = mk_request("POST", f"{AGENCY_BASE}/auth/login", data={"email": "david@magnify.ing", "password": "password123"})
    if status == 200:
        print_result("Agency", "Login válido admin", "PASS", "Token received")
        token = json.loads(body).get("access_token")
        
        # Get CSRF Cookie
         # Look at Set-Cookie headers
        csrf_token = None
        for k, v in headers.items():
            if k.lower() == 'set-cookie':
                if 'agency_csrf_token=' in v:
                    csrf_token = v.split('agency_csrf_token=')[1].split(';')[0]
    else:
        print_result("Agency", "Login válido admin", "FAIL", f"Status: {status}")
        return

    headers_auth = {
        "Authorization": f"Bearer {token}",
        "X-CSRF-Token": csrf_token if csrf_token else ""
    }
    
    # Dashboard
    status, body, _ = mk_request("GET", f"{AGENCY_BASE}/dashboard", headers=headers_auth)
    print_result("Agency", "Dashboard Principal Carga (API)", "PASS" if status == 200 else "FAIL", f"Status: {status}")

    # Tarea Completa
    temp_task = {"title": "Test Task", "status": "todo", "category_id": 1, "description": "test", "color": "#000000"}
    status, body, _ = mk_request("POST", f"{AGENCY_BASE}/tasks", data=temp_task, headers=headers_auth)
    if status == 201:
        task_id = json.loads(body).get("id")
        print_result("Agency", "Crear tarea", "PASS", f"Task ID {task_id}")
        
        status2, body2, _ = mk_request("PATCH", f"{AGENCY_BASE}/tasks/{task_id}/status", data={"status": "done"}, headers=headers_auth)
        # Using correct endpoint? The PUT required all fields, let's just see if patching works or put.
    else:
        print_result("Agency", "Crear tarea", "FAIL", f"Status: {status}")

    # Member Access check
    status_m, body_m, head_m = mk_request("POST", f"{AGENCY_BASE}/auth/login", data={"email": "nacho@magnify.ing", "password": "password123"})
    if status_m == 200:
        member_headers = {"Authorization": f"Bearer {json.loads(body_m).get('access_token')}"}
        status_v, _, _ = mk_request("GET", f"{AGENCY_BASE}/vault", headers=member_headers)
        if status_v in [401, 403]:
            print_result("Agency", "Vault acceso no admin bloqueado", "PASS", f"Status: {status_v}")
        else:
            print_result("Agency", "Vault acceso no admin bloqueado", "FAIL", f"Status: {status_v} - Should be 403")
    else:
         print_result("Agency", "Member login", "FAIL", f"Status: {status_m}")

if __name__ == "__main__":
    test_agency()
