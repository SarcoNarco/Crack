FROM python:3.12-slim

WORKDIR /workspace

COPY coordinator/requirements.txt /workspace/coordinator/requirements.txt
RUN pip install --no-cache-dir -r /workspace/coordinator/requirements.txt

COPY coordinator /workspace/coordinator
COPY ledger /workspace/ledger
COPY agents /workspace/agents
COPY scope-controller /workspace/scope-controller
COPY reports /workspace/reports
COPY ui /workspace/ui
COPY app-under-test/app /workspace/app-under-test/app
COPY app-under-test/scripts /workspace/app-under-test/scripts

RUN mkdir -p /workspace/data /workspace/demo/output /workspace/reports/output /workspace/app-under-test/data

ENV PYTHONPATH=/workspace:/workspace/agents/router:/workspace/agents/mapper:/workspace/scope-controller

EXPOSE 8000

CMD ["uvicorn", "coordinator.main:app", "--host", "0.0.0.0", "--port", "8000"]
