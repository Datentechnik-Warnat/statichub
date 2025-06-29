from flask import Flask, request, jsonify
import docker
import os
import logging
from pathlib import Path
from datetime import datetime
import uuid

# Logging konfigurieren
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Konfiguration für den Compiler
COMPILER_CONFIG = {
    'image': 'hugomods/hugo:debian-ci-0.147.9',
    'command': 'hugo --gc --minify --baseURL "https://{domain}/"',
    'working_dir': '/repo',
    'entrypoint': '/bin/sh'
}

PAGES_ROOT = "/statichosts/pages"

# Docker Client initialisieren
try:
    docker_client = docker.from_env()
    logger.info("Docker Client erfolgreich initialisiert")
except Exception as e:
    logger.error(f"Fehler beim Initialisieren des Docker Clients: {e}")
    docker_client = None

def write_deploy_log(domain, deploy_id, step, output, error=None):
    """
    Schreibt Deploy-Logs in eine Datei
    """
    try:
        # Log-Verzeichnis erstellen
        log_dir = Path(PAGES_ROOT) / domain / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # Log-Datei für diesen Deploy-Vorgang
        log_file = log_dir / f"deploy_{deploy_id}.log"
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n=== {step.upper()} - {timestamp} ===\n")
            if output:
                f.write(f"STDOUT:\n{output}\n")
            if error:
                f.write(f"STDERR:\n{error}\n")
            f.write("=" * 50 + "\n")
            
    except Exception as e:
        logger.error(f"Fehler beim Schreiben des Deploy-Logs: {e}")

@app.route('/deploy/<domain>', methods=['POST'])
def deploy_static_site(domain):
    """
    Deployed eine statische Website für die angegebene Domain
    """
    # Eindeutige Deploy-ID generieren
    deploy_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    secret = request.args.get('secret')

    if secret != os.getenv("SECRET_KEY"):
        return "Access Forbidden", 401

    try:
        # Validierung der Domain (einfache Überprüfung)
        if not domain or not domain.replace('.', '').replace('-', '').isalnum():
            return jsonify({
                'error': 'Ungültige Domain',
                'domain': domain
            }), 400
        
        # Pfade definieren
        base_path = Path(PAGES_ROOT)
        domain_path = base_path / domain
        repo_path = domain_path / "repository"
        public_source = repo_path / "public"
        public_dest = domain_path / "public"
        
        logger.info(f"Deployment für Domain: {domain} (Deploy-ID: {deploy_id})")
        logger.info(f"Repository Pfad: {repo_path}")
        
        # Deploy-Start in Log schreiben
        write_deploy_log(domain, deploy_id, "deploy_start", 
                        f"Deploy gestartet für Domain: {domain}\nDeploy-ID: {deploy_id}\nRepository: {repo_path}")
        
        # Überprüfen ob Docker Client verfügbar ist
        if not docker_client:
            write_deploy_log(domain, deploy_id, "error", "Docker Client nicht verfügbar")
            return jsonify({
                'error': 'Docker Client nicht verfügbar'
            }), 500
        
        # Verzeichnisse erstellen falls sie nicht existieren
        repo_path.mkdir(parents=True, exist_ok=True)

        # Schritt 1: Docker Container für Git Pull ausführen
        try:
            # Alpine Linux mit Git verwenden
            container = docker_client.containers.run(
                image='alpine/git:latest',
                command='pull origin release',
                volumes={
                    str(repo_path): {
                        'bind': '/repo',
                        'mode': 'rw'
                    }
                },
                user='1000', 
                working_dir="/repo",
                remove=True,  # Container nach Ausführung entfernen
                detach=False,  # Warten bis Container fertig ist
                stdout=True,
                stderr=True
            )
            
            # Container Output dekodieren
            output = container.decode('utf-8') if container else ""
            write_deploy_log(domain, deploy_id, "git_pull", output)
            
            logger.info(f"Git pull erfolgreich für {domain}")
            
        except docker.errors.ContainerError as e:
            error_msg = str(e)
            write_deploy_log(domain, deploy_id, "git_pull_warning", 
                           f"Git pull fehlgeschlagen (möglicherweise kein Git Repository)", error_msg)
            logger.warning(f"Git pull fehlgeschlagen (möglicherweise kein Git Repository): {e}")
            # Weitermachen, falls es kein Git Repository ist
        except Exception as e:
            error_msg = str(e)
            write_deploy_log(domain, deploy_id, "git_pull_error", "", error_msg)
            logger.error(f"Docker Container Fehler: {e}")
            return jsonify({
                'error': f'Docker Container Fehler: {str(e)}',
                'domain': domain,
                'deploy_id': deploy_id
            }), 500
        
        # Schritt 2: Hugo Compiler ausführen
        try:
            # Befehl für die spezifische Domain anpassen
            hugo_command = COMPILER_CONFIG['command'].format(domain=domain)
            
            compiler_container = docker_client.containers.run(
                image=COMPILER_CONFIG['image'],
                command=['-c', hugo_command],
                volumes={
                    str(repo_path): {
                        'bind': '/repo',
                        'mode': 'rw'
                    }
                },
                working_dir=COMPILER_CONFIG['working_dir'],
                entrypoint=COMPILER_CONFIG['entrypoint'],
                user='1000', 
                remove=True,
                detach=False,
                stdout=True,
                stderr=True
            )
            
            # Container Output dekodieren
            output = compiler_container.decode('utf-8') if compiler_container else ""
            write_deploy_log(domain, deploy_id, "hugo_compile", output)
            
            logger.info(f"Hugo Compiler erfolgreich ausgeführt für {domain}")
            
        except docker.errors.ContainerError as e:
            error_msg = str(e)
            write_deploy_log(domain, deploy_id, "hugo_compile_error", "", error_msg)
            logger.error(f"Hugo Compiler fehlgeschlagen: {e}")
            return jsonify({
                'error': f'Hugo Compiler Fehler: {str(e)}',
                'domain': domain,
                'deploy_id': deploy_id
            }), 500
        except Exception as e:
            error_msg = str(e)
            write_deploy_log(domain, deploy_id, "hugo_compile_error", "", error_msg)
            logger.error(f"Unerwarteter Compiler Fehler: {e}")
            return jsonify({
                'error': f'Compiler Fehler: {str(e)}',
                'domain': domain,
                'deploy_id': deploy_id
            }), 500
        
        # Schritt 3: Public Verzeichnis mit rsync synchronisieren
        if public_source.exists():
            # Zielverzeichnis erstellen falls es nicht existiert
            public_dest.mkdir(parents=True, exist_ok=True)
            
            try:
                # rsync Container für Dateiübertragung
                rsync_container = docker_client.containers.run(
                    image='secoresearch/rsync:latest',
                    command='rsync -a --delete /source/ /destination/',
                    volumes={
                        str(public_source): {
                            'bind': '/source',
                            'mode': 'ro'
                        },
                        str(public_dest): {
                            'bind': '/destination',
                            'mode': 'rw'
                        }
                    },
                    user='1000', 
                    remove=True,
                    detach=False,
                    stdout=True,
                    stderr=True
                )
                
                # Container Output dekodieren
                output = rsync_container.decode('utf-8') if rsync_container else ""
                write_deploy_log(domain, deploy_id, "rsync", output)
                
                logger.info(f"Rsync erfolgreich: {public_source} -> {public_dest}")
                
                # Deploy erfolgreich abgeschlossen
                write_deploy_log(domain, deploy_id, "deploy_success", 
                               f"Deploy erfolgreich abgeschlossen\nPublic Path: {public_dest}")
                
                return jsonify({
                    'success': True,
                    'message': f'Deployment für {domain} erfolgreich (Git Pull + Hugo Compiler + Rsync)',
                    'domain': domain,
                    'deploy_id': deploy_id,
                    'repository_path': str(repo_path),
                    'public_path': str(public_dest),
                    'steps_completed': ['git_pull', 'hugo_compile', 'rsync'],
                    'compiler_image': COMPILER_CONFIG['image']
                }), 200
                
            except docker.errors.ContainerError as e:
                error_msg = str(e)
                write_deploy_log(domain, deploy_id, "rsync_error", "", error_msg)
                logger.error(f"Rsync Container Fehler: {e}")
                return jsonify({
                    'error': f'Rsync Fehler: {str(e)}',
                    'domain': domain,
                    'deploy_id': deploy_id
                }), 500
            except Exception as e:
                error_msg = str(e)
                write_deploy_log(domain, deploy_id, "rsync_error", "", error_msg)
                logger.error(f"Unerwarteter Rsync Fehler: {e}")
                return jsonify({
                    'error': f'Rsync Fehler: {str(e)}',
                    'domain': domain,
                    'deploy_id': deploy_id
                }), 500
        else:
            error_msg = f"Public Verzeichnis nicht gefunden nach Hugo Compiler: {public_source}"
            write_deploy_log(domain, deploy_id, "deploy_error", "", error_msg)
            logger.warning(error_msg)
            return jsonify({
                'error': error_msg,
                'domain': domain,
                'deploy_id': deploy_id,
                'hint': 'Möglicherweise ist der Hugo Build fehlgeschlagen oder das Ausgabeverzeichnis ist anders konfiguriert'
            }), 404
            
    except Exception as e:
        error_msg = str(e)
        write_deploy_log(domain, deploy_id, "deploy_error", "", error_msg)
        logger.error(f"Unerwarteter Fehler beim Deployment: {e}")
        return jsonify({
            'error': f'Unerwarteter Fehler: {str(e)}',
            'domain': domain,
            'deploy_id': deploy_id
        }), 500

@app.route('/logs/<domain>', methods=['GET'])
def get_deploy_logs(domain):
    """
    Gibt die Deploy-Logs für eine Domain zurück
    """
    secret = request.args.get('secret')

    if secret != os.getenv("SECRET_KEY"):
        return "Access Forbidden", 401

    try:
        log_dir = Path(PAGES_ROOT) / domain / "logs"
        
        if not log_dir.exists():
            return jsonify({
                'error': f'Keine Logs für Domain {domain} gefunden',
                'domain': domain
            }), 404
        
        # Alle Log-Dateien auflisten
        log_files = []
        for log_file in log_dir.glob("deploy_*.log"):
            try:
                stat = log_file.stat()
                log_files.append({
                    'filename': log_file.name,
                    'deploy_id': log_file.stem.replace('deploy_', ''),
                    'size': stat.st_size,
                    'created': datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
            except Exception as e:
                logger.error(f"Fehler beim Lesen der Log-Datei {log_file}: {e}") 
        
        # Nach Erstellungsdatum sortieren (neueste zuerst)
        latest_log = max(log_files, key=lambda x: x['created'])
        
        deploy_id = latest_log["deploy_id"]

        log_file = Path(PAGES_ROOT) / domain / "logs" / f"deploy_{deploy_id}.log"
        
        if not log_file.exists():
            return f"Log-Datei für Deploy-ID {deploy_id} nicht gefunden", 404
        
        # Log-Inhalt lesen und als Plain Text zurückgeben
        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return content, 200, {'Content-Type': 'text/plain; charset=utf-8'}

        
    except Exception as e:
        return jsonify({
            'error': f'Fehler beim Abrufen der Logs: {str(e)}',
            'domain': domain
        }), 500

@app.route('/logs/<domain>/<deploy_id>', methods=['GET'])
def get_deploy_log_raw(domain, deploy_id):
    """
    Gibt den rohen Inhalt einer Deploy-Log-Datei zurück (als Plain Text)
    """
    secret = request.args.get('secret')

    if secret != os.getenv("SECRET_KEY"):
        return "Access Forbidden", 401

    try:
        log_file = Path(PAGES_ROOT) / domain / "logs" / f"deploy_{deploy_id}.log"
        
        if not log_file.exists():
            return f"Log-Datei für Deploy-ID {deploy_id} nicht gefunden", 404
        
        # Log-Inhalt lesen und als Plain Text zurückgeben
        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return content, 200, {'Content-Type': 'text/plain; charset=utf-8'}
        
    except Exception as e:
        return f"Fehler beim Lesen der Log-Datei: {str(e)}", 500

@app.route('/status/<domain>', methods=['GET'])
def get_status(domain):
    """
    Gibt den Status einer Domain zurück
    """
    secret = request.args.get('secret')

    if secret != os.getenv("SECRET_KEY"):
        return "Access Forbidden", 401

    try:
        base_path = Path(PAGES_ROOT)
        domain_path = base_path / domain
        repo_path = domain_path / "repository"
        public_path = domain_path / "public"
        log_path = domain_path / "logs"
        
        status = {
            'domain': domain,
            'repository_exists': repo_path.exists(),
            'public_exists': public_path.exists(),
            'logs_exists': log_path.exists(),
            'repository_path': str(repo_path),
            'public_path': str(public_path),
            'logs_path': str(log_path),
            'compiler_config': COMPILER_CONFIG
        }
        
        # Log-Statistiken hinzufügen
        if log_path.exists():
            log_files = list(log_path.glob("deploy_*.log"))
            status['log_count'] = len(log_files)
            if log_files:
                # Neueste Log-Datei finden
                latest_log = max(log_files, key=lambda x: x.stat().st_mtime)
                status['latest_deploy'] = {
                    'deploy_id': latest_log.stem.replace('deploy_', ''),
                    'timestamp': datetime.fromtimestamp(latest_log.stat().st_mtime).isoformat()
                }
        else:
            status['log_count'] = 0
        
        if repo_path.exists():
            # Git Repository Info hinzufügen
            try:
                container = docker_client.containers.run(
                    image='alpine/git:latest',
                    command='log -1 --pretty=format:"%H,%an,%ad" --date=iso',
                    volumes={
                        str(repo_path): {
                            'bind': '/repo',
                            'mode': 'ro'
                        }
                    },
                    working_dir="/repo",
                    user='1000',
                    remove=True,
                    detach=False,
                    stdout=True,
                    stderr=True
                )
                
                if container:
                    commit_info = container.decode('utf-8').strip().split(',')
                    if len(commit_info) >= 3:
                        status['last_commit'] = {
                            'hash': commit_info[0],
                            'author': commit_info[1],
                            'date': commit_info[2]
                        }
            except Exception as e:
                print(e)
                pass  # Falls Git Infos nicht verfügbar sind
        
        return jsonify(status), 200
        
    except Exception as e:
        return jsonify({
            'error': f'Fehler beim Abrufen des Status: {str(e)}',
            'domain': domain
        }), 500

@app.route('/caddy-check', methods=['GET'])
def caddy_domain_check():
    """
    Endpunkt für Caddy on_demand_tls
    Überprüft ob eine Domain/Subdomain existiert
    Entfernt www. Präfix falls vorhanden
    Domain wird als ?domain= Parameter übergeben
    """
    try:
        # Domain aus Query Parameter extrahieren
        domain = request.args.get('domain')
        
        if not domain:
            logger.warning("Caddy Check: Keine Domain im Query Parameter")
            return "", 400
        
        # www. Präfix entfernen falls vorhanden
        clean_domain = domain
        if domain.startswith('www.'):
            clean_domain = domain[4:]
            logger.info(f"Entferne www. Präfix: {domain} -> {clean_domain}")
        
        # Pfad zur Domain überprüfen
        base_path = Path(PAGES_ROOT)
        domain_path = base_path / clean_domain
        public_path = domain_path / "public"
        
        logger.info(f"Caddy Check für Domain: {domain} (clean: {clean_domain})")
        logger.info(f"Überprüfe Pfad: {public_path}")
        
        # Überprüfen ob das public Verzeichnis existiert
        if public_path.exists() and public_path.is_dir():
            logger.info(f"Domain {domain} gefunden - Caddy TLS erlaubt")
            return "ok", 200
        else:
            logger.info(f"Domain {domain} nicht gefunden - Caddy TLS verweigert")
            return "", 404
            
    except Exception as e:
        logger.error(f"Fehler beim Caddy Domain Check für {domain}: {e}")
        return "", 404

@app.route('/health', methods=['GET'])
def health_check():
    """
    Gesundheitscheck der Anwendung
    """
    try:
        # Docker Client testen
        docker_client.ping()
        docker_status = "OK"
    except:
        docker_status = "ERROR"
    
    return jsonify({
        'status': 'OK',
        'docker': docker_status,
        'compiler_config': COMPILER_CONFIG
    }), 200

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint nicht gefunden'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Interner Server Fehler'}), 500

if __name__ == '__main__':
    # Überprüfen ob /statichost Verzeichnis existiert
    statichost_path = Path(PAGES_ROOT)
    if not statichost_path.exists():
        logger.warning(f"Statichost Verzeichnis existiert nicht: {statichost_path}")
        logger.info("Erstelle Statichost Verzeichnis für Tests...")
        statichost_path.mkdir(parents=True, exist_ok=True)
    
    # Flask App starten (nur für Development)
    # In Production wird Gunicorn verwendet
    app.run(debug=True, host='0.0.0.0', port=8080)