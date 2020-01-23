FROM python:3 AS build
RUN pip install poetry
COPY . /tmp
WORKDIR /tmp
RUN poetry build
# This doesn't work with dependencies from git
# RUN poetry export --format requirements.txt -o dist/requirements.txt

FROM python:3-slim
COPY --from=build /tmp/dist /tmp
COPY config.py /etc/hypercorn.py
# RUN pip install -r /tmp/requirements.txt
RUN pip install /tmp/manage-*.whl
ARG extra_pkgs
# Is there a better way to do this without leaving extra files?
RUN ["python", "-c", "import os, json\npkgs = json.loads(os.environ.get('extra_pkgs') or '[]')\nif pkgs: os.execv('/usr/local/bin/pip', ['pip', 'install', *pkgs])"]

VOLUME ["/mc/world", "/mc/snapshot", "/mc/server.properties"]
CMD ["hypercorn", "--config", "python:/etc/hypercorn.py", "manage.app:entrypoint"]
EXPOSE 80
