import uuid
import subprocess
import shlex
import atexit
import validators
import string
import logging

from multiprocessing import Lock, Process
from multiprocessing.managers import AcquirerProxy, BaseManager, ListProxy

from time import sleep

from functools import partial

from flask import Flask, render_template, request, send_file

shared_list = []
shared_lock = Lock()

logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


def lister():
    return shared_list


def acquirer():
    return shared_lock


def get_shared_state(host, port, key):
    manager = BaseManager((host, port), key)
    manager.register("get_list", lister, ListProxy)
    manager.register("get_lock", acquirer, AcquirerProxy)
    try:
        manager.get_server()
        manager.start()
    except OSError:  # Address already in use
        manager.connect()
    return manager.get_list(), manager.get_lock()


def create_app(
    vms=8,
    image='registry.lil.tools/harvardlil/spoon:0.1.2',
    cpus=2,
    memory=1,
    size=6,
    dryrun=False
):
    """
    Warms up a pool of VMs, listens for requests, spins up new VMs as
    needed to maintain target pool size
    """

    # prepare pool structure; ~consider using a per-run key, which might~
    # ~give a clue if we leak the process and try to compete for the~
    # ~same port~ -- no! in the case of a WSGI server, we need (?) separate
    # instances of this application to share a pool
    HOST = "127.0.0.1"
    PORT = 35791
    KEY = b"secret"
    shared_list, shared_lock = get_shared_state(HOST, PORT, KEY)

    spec = Specs(image, cpus, memory, size, dryrun)

    # warm up pool if it hasn't been done already
    for _ in range(vms):
        if vm := ignite(spec):
            with shared_lock:
                if len(shared_list) < vms:
                    shared_list.append(vm)

    with shared_lock:
        logger.info(f'pool is now {shared_list}')

    # start thread/process for repopulating pool
    p = Process(target=repopulate, args=(shared_lock, shared_list, vms, spec))
    p.start()

    def cleanup(dryrun, process):
        # shut down all VMs in pool here
        with shared_lock:
            for vm in shared_list:
                douse(vm, dryrun)
        # shut down the repopulation thread
        process.join()
        process.close()
        logger.info('Closed repopulation process')

    atexit.register(cleanup, dryrun, p)

    # start Flask app
    app = Flask(__name__)

    @app.route("/", methods=['GET', 'POST'])
    def hello():
        if request.method == 'GET':
            # show the form
            return render_template('index.html')
        else:
            url = request.form['url']
            assert validators.url(url)
            with shared_lock:
                try:
                    vm = shared_list.pop()
                    logger.info(f'popped { vm }')
                    logger.info(f'pool is now { shared_list }')
                except IndexError:
                    return 'No VM available; please retry.'
            capture(vm, url, dryrun)
            url = url.translate(
                str.maketrans(
                    string.punctuation,
                    '_'*len(string.punctuation)
                )
            )
            filename = f'{ url }-{ vm }.wacz'
            if not dryrun:
                send_file(
                    f'/tmp/{ vm }.wacz',
                    as_attachment=True,
                    download_name=filename
                )
            else:
                return filename

    return app


# this partially-applied function is for use in development, since you can't
# pass arguments to an application run with waitress-serve
create_app_dev = partial(create_app, dryrun=True)


class Specs:
    def __init__(self, image, cpus, memory, size, dryrun):
        self.image = image
        self.cpus = cpus
        self.memory = memory
        self.size = size
        self.dryrun = dryrun


def repopulate(shared_lock, shared_list, vms, spec):
    while True:
        with shared_lock:
            if len(shared_list) < vms:
                if vm := ignite(spec):
                    shared_list.append(vm)
                    logger.info(f'pool is now {shared_list}')

        sleep(1)


def ignite(spec):
    """
    Spin up a VM and return its name
    """
    name = str(uuid.uuid1())
    if spec.dryrun:
        cmd = f'echo {name}'
    else:
        cmd = f'sudo ignite create { spec.image } --name { name } --cpus { spec.cpus } --memory { spec.memory }GB --size { spec.size }GB --ssh && sudo ignite start { name }'  # noqa
    try:
        result = subprocess.run(shlex.split(cmd), capture_output=True)
        if result.returncode == 0:
            logger.info(f'added VM {name}')
            return name
        else:
            logger.warning(f"Couldn't ignite a VM: {result.stderr}")
            return None
    except Exception as e:  # which?
        logger.warning(f"Couldn't ignite a VM: {e}")
        return None


def douse(name, dryrun):
    logging.info(f'shutting down {name}')
    if dryrun:
        return
    cmd = f'sudo ignite stop { name } && sudo ignite rm { name }'
    return subprocess.run(shlex.split(cmd), capture_output=True)


def capture(vm, url, dryrun):
    cmd = f'sudo ignite exec { vm } "xvfb-run --auto-servernum -- scoop \"{ url }\" --headless false" && sudo ignite cp { vm }:/root/archive.wacz /tmp/{ vm }.wacz'  # noqa
    try:
        result = subprocess.run(shlex.split(cmd), capture_output=True)
        if result.returncode == 0:
            return vm
    except Exception as e:  # which?
        logger.warning(f"Couldn't capture: {e}")
        raise
    finally:
        p = Process(target=douse, args=(vm, dryrun))
        p.start()
