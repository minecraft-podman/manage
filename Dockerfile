FROM python:3 AS build
RUN pip install poetry
COPY . /tmp
WORKDIR /tmp
RUN poetry build
RUN poetry export --format requirements.txt -o dist/requirements.txt

FROM python:3-slim
COPY --from=build /tmp/dist /tmp
RUN pip install -r /tmp/requirements.txt
RUN pip install /tmp/manage-*.whl

VOLUME ["/mc/world", "/mc/snapshot", "/mc/server.properties"]
CMD ["hypercorn", "-b", "0.0.0.0:80", "manage.app:entrypoint"]
EXPOSE 80
