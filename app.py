from playwright.sync_api import sync_playwright, Error as PlaywrightError
import os
import json
from datetime import datetime, timedelta
import base64
import requests
import atexit
from apscheduler.schedulers.background import BackgroundScheduler
import time
from PIL import Image, ImageDraw, ImageFont
import logging
import glob

# Configuração de logging
LOG_DIR = 'logs'
os.makedirs(LOG_DIR, exist_ok=True)
log_file = os.path.join(LOG_DIR, f"screenshot_rotator_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    encoding='utf-8'
)

console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger('').addHandler(console)

def log_print(message):
    logging.info(message)

# Limpa logs antigos (> 2 dias)
def clean_old_logs():
    now = datetime.now()
    for f in glob.glob(os.path.join(LOG_DIR, 'screenshot_rotator_*.log')):
        try:
            file_time_str = os.path.basename(f).split('_')[2].split('.')[0]
            file_time = datetime.strptime(file_time_str, '%Y%m%d%H%M%S')
            if now - file_time > timedelta(days=2):
                os.remove(f)
                log_print(f"[LIMPEZA] Log antigo deletado: {f}")
        except:
            pass
clean_old_logs()

# Configurações
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    log_print("[AVISO] GITHUB_TOKEN não definido – uploads e deleções desabilitados")
GITHUB_OWNER = "sfarinajr"
GITHUB_REPO = "ipad-dashboard"
SCREENSHOTS_DIR = 'screenshots'
ERROR_IMAGE_TEMPLATE = "erro de site.png"
STATE_FILE = 'state.json'
SITES_FILE = 'sites.txt'

sites = []
def load_sites():
    global sites
    if not os.path.exists(SITES_FILE):
        log_print(f"ERRO: {SITES_FILE} não encontrado!")
        return
    with open(SITES_FILE, 'r', encoding='utf-8') as f:
        sites = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
    log_print(f"[START] Carregados {len(sites)} sites")
load_sites()
if not sites:
    log_print("[FATAL] Nenhum site carregado. Abortando.")
    exit(1)

if not os.path.exists(SCREENSHOTS_DIR):
    os.makedirs(SCREENSHOTS_DIR)

def get_current_index():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
                return data.get('current_index', 0)
        except Exception as e:
            log_print(f"[ERRO] Falha ao ler state.json: {e}")
    return 0

def save_current_index(index):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump({'current_index': index}, f)
        log_print(f"[STATE] Índice salvo: {index}")
    except Exception as e:
        log_print(f"[ERRO] Falha ao salvar state.json: {e}")

def handle_cookie_banner(page):
    accept_selectors = [
        'button:has-text("ACEITAR")', 'button:has-text("Aceitar todos")',
        'button:has-text("OK")', 'button:has-text("Entendi e fechar")',
        'button:has-text("Entendi e fechar")', 'button:has-text("Continuar")',
        'button:has-text("Allow")', 'button:has-text("Agree")',
        'button:has-text("Accept all")', '[aria-label*="aceitar"]',
        '[aria-label*="cookies"] button', '#onetrust-accept-btn-handler',
        '.cookie-accept', '[id*="cookie"][id*="accept"]',
        '[class*="cookie"][class*="accept"]',
    ]
    clicked = False
    for sel in accept_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=4000):
                log_print(f"[COOKIE] Clicando aceitar: {sel}")
                btn.click(timeout=5000)
                page.wait_for_timeout(2000)
                clicked = True
                break
        except:
            pass
    
    if not clicked:
        reject_selectors = [
            'button:has-text("Rejeitar")', 'button:has-text("Recusar")',
            'button:has-text("Não aceito")', 'button:has-text("Fechar")',
            'button:has-text("Close")', 'button:has-text("Cancelar")',
            '[aria-label*="rejeitar"]', '[aria-label*="close"]',
            '[aria-label*="decline"]', '.close', '[class*="reject"]',
            '[class*="decline"]', '[id*="reject"]', '[id*="decline"]',
        ]
        for sel in reject_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=3000):
                    log_print(f"[COOKIE] Clicando rejeitar/fechar: {sel}")
                    btn.click(timeout=5000)
                    page.wait_for_timeout(2000)
                    return
            except:
                pass
    
    try:
        page.evaluate("""
            () => {
                const banners = document.querySelectorAll('[id*="cookie"], [class*="cookie"], [aria-label*="cookie"]');
                banners.forEach(b => b.style.display = 'none');
            }
        """)
        log_print("[COOKIE] Tentativa JS de esconder banner")
    except:
        pass
    log_print("[COOKIE] Tratamento concluído")

def create_error_image(url):
    if not os.path.exists(ERROR_IMAGE_TEMPLATE):
        log_print(f"[ERRO] Base {ERROR_IMAGE_TEMPLATE} não encontrada")
        return None
    try:
        img = Image.open(ERROR_IMAGE_TEMPLATE)
        draw = ImageDraw.Draw(img)
        font_size = 180
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except:
            font = ImageFont.load_default()
            font_size = 60
        text = url
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (img.width - text_w) // 2
        y = (img.height - text_h) // 2
        draw.text((x, y), text, fill="black", font=font)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        path = os.path.join(SCREENSHOTS_DIR, f"error_{ts}.png")
        img.save(path)
        log_print(f"[FALHA FINAL] Imagem de erro salva: {path}")
        return path
    except Exception as e:
        log_print(f"[ERRO GRAVE] Falha ao criar imagem de erro: {e}")
        return None

def take_screenshot(index):
    url = sites[index]
    log_print(f"[SCREENSHOT INÍCIO] {url} (site {index+1}/{len(sites)})")
    path = None
    MAX_RETRIES = 3
    TIMEOUT_PER_TRY = 100000
    
    for attempt in range(1, MAX_RETRIES + 1):
        log_print(f" Tentativa {attempt}/{MAX_RETRIES}")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=[
                    '--no-sandbox', '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage', '--disable-gpu',
                    '--disable-extensions'
                ])
                context = browser.new_context(viewport={'width': 1024, 'height': 768})
                page = context.new_page()
                page.goto(url, wait_until='domcontentloaded', timeout=TIMEOUT_PER_TRY)
                
                try:
                    handle_cookie_banner(page)
                except Exception as cookie_err:
                    log_print(f"[COOKIE] Erro ao tratar banner: {cookie_err} → Continuando")
                
                page.wait_for_timeout(10000)
                
                fname = f"screenshot{index+1:03d}.png"
                path = os.path.join(SCREENSHOTS_DIR, fname)
                page.screenshot(path=path)
                log_print(f" SUCESSO → {fname}")
                browser.close()
                break
                
        except PlaywrightError as pe:
            log_print(f" PlaywrightError tentativa {attempt}: {pe}")
            if attempt == MAX_RETRIES:
                path = create_error_image(url)
                time.sleep(10)
        except Exception as e:
            log_print(f" Erro geral tentativa {attempt}: {e}")
            if attempt == MAX_RETRIES:
                path = create_error_image(url)
                time.sleep(10)
    
    log_print(f"[SCREENSHOT FIM] path final = {path}")
    return path

def delete_old_github_files_for_index(index):
    if not GITHUB_TOKEN:
        return False
    try:
        api_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents"
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        resp = requests.get(api_url, headers=headers, timeout=12)
        if resp.status_code != 200:
            log_print(f"[DELETE] Falha ao listar pasta raiz: {resp.status_code}")
            return False
        
        items = resp.json()
        prefix = f"screenshot{index+1:03d}"
        deleted_any = False
        
        for item in items:
            if item.get("type") == "file" and item["name"].startswith(prefix):
                file_url = item["url"]
                sha = item["sha"]
                delete_payload = {
                    "message": f"Remove screenshot antigo - {item['name']}",
                    "sha": sha,
                    "committer": {"name": "Dashboard Bot", "email": "bot@local"}
                }
                del_resp = requests.delete(file_url, headers=headers, json=delete_payload, timeout=12)
                if del_resp.status_code in (200, 204):
                    log_print(f"[DELETE GITHUB] OK → {item['name']}")
                    deleted_any = True
                else:
                    log_print(f"[DELETE GITHUB] Falha {del_resp.status_code} → {item['name']}")
        return deleted_any
    except Exception as e:
        log_print(f"[DELETE GITHUB] Erro: {str(e)}")
        return False

def upload_to_github(local_path, filename):
    if not GITHUB_TOKEN:
        log_print("[UPLOAD] GITHUB_TOKEN não definido")
        return False
    try:
        with open(local_path, 'rb') as f:
            content = base64.b64encode(f.read()).decode('utf-8')
        
        api_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{filename}"
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        
        resp = requests.get(api_url, headers=headers, timeout=10)
        sha = None
        if resp.status_code == 200:
            sha = resp.json().get("sha")
        
        payload = {
            "message": f"Atualiza screenshot - {filename}",
            "content": content,
            "committer": {"name": "Dashboard Bot", "email": "bot@local"}
        }
        if sha:
            payload["sha"] = sha
        
        resp = requests.put(api_url, headers=headers, json=payload, timeout=15)
        if resp.status_code in (200, 201):
            log_print(f"[UPLOAD] Sucesso → {filename}")
            return True
        else:
            log_print(f"[UPLOAD] Falha: {resp.status_code} - {resp.text[:180]}")
            return False
    except Exception as e:
        log_print(f"[UPLOAD] Erro: {str(e)}")
        return False

def update_images_list_file():
    if not GITHUB_TOKEN:
        return
    try:
        pattern = os.path.join(SCREENSHOTS_DIR, "screenshot*.png")
        local_files = sorted(
            [os.path.basename(f) for f in glob.glob(pattern) if "error_" not in os.path.basename(f)],
            reverse=True
        )
        if not local_files:
            return
        
        content_str = "\n".join(local_files) + "\n"
        content_base64 = base64.b64encode(content_str.encode('utf-8')).decode('utf-8')
        manifest_filename = "imagensPNG.txt"
        api_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{manifest_filename}"
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        
        resp = requests.get(api_url, headers=headers, timeout=10)
        sha = None
        if resp.status_code == 200:
            sha = resp.json().get("sha")
        
        payload = {
            "message": f"Atualiza lista de imagens - {len(local_files)} screenshots",
            "content": content_base64,
            "committer": {"name": "Dashboard Bot", "email": "bot@local"}
        }
        if sha:
            payload["sha"] = sha
        
        resp = requests.put(api_url, headers=headers, json=payload, timeout=15)
        if resp.status_code in (200, 201):
            log_print(f"[MANIFEST] Atualizado → {len(local_files)} imagens")
        else:
            log_print(f"[MANIFEST] Falha: {resp.status_code}")
    except Exception as e:
        log_print(f"[MANIFEST] Erro: {str(e)}")

def scheduled_screenshot():
    log_print(f"===== CICLO INICIADO {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====")
    current_index = get_current_index()
    
    path = take_screenshot(current_index)
    uploaded = False
    
    if path and "error_" not in os.path.basename(path):
        filename = os.path.basename(path)
        delete_old_github_files_for_index(current_index)
        uploaded = upload_to_github(path, filename)
        
        if uploaded:
            # Limpa screenshots antigos do mesmo índice localmente
            pattern = os.path.join(SCREENSHOTS_DIR, f"screenshot{current_index+1:03d}*.png")
            for f in glob.glob(pattern):
                if f != path:
                    try:
                        os.remove(f)
                        log_print(f"[LIMPEZA LOCAL] Removido: {os.path.basename(f)}")
                    except:
                        pass
    
    update_images_list_file()
    
    # Limpa imagens de erro após cada screenshot
    for f in glob.glob(os.path.join(SCREENSHOTS_DIR, "error_*")):
        try:
            os.remove(f)
            log_print(f"[LIMPEZA] Erro deletado: {os.path.basename(f)}")
        except:
            pass
    
    next_index = (current_index + 1) % len(sites)
    save_current_index(next_index)
    log_print(f"===== CICLO FINALIZADO → Próximo: {next_index+1} =====\n")

# Scheduler
scheduler = BackgroundScheduler(max_instances=1)
scheduler.add_job(scheduled_screenshot, 'interval', minutes=5)
scheduler.start()
log_print("[SCHEDULER] Iniciado – intervalo 5 minutos")

# Primeiro ciclo imediato
log_print("[TESTE IMEDIATO] Executando primeiro ciclo agora...")
scheduled_screenshot()

atexit.register(scheduler.shutdown)

if __name__ == '__main__':
    log_print("=== SCRIPT INICIADO ===")
    log_print(f" - Total sites: {len(sites)}")
    try:
        while True:
            log_print(f"[VIVO] {datetime.now().strftime('%H:%M:%S')} - ativo")
            time.sleep(60)
    except KeyboardInterrupt:
        log_print("[STOP] Encerrando...")
        scheduler.shutdown()
        log_print("Finalizado.")
