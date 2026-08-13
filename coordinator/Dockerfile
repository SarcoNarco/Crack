FROM python:3.12-slim

WORKDIR /workspace

COPY coordinator/requirements.txt /workspace/coordinator/requirements.txt
RUN pip install --no-cache-dir -r /workspace/coordinator/requirements.txt

COPY coordinator /workspace/coordinator
COPY ledger /workspace/ledger

EXPOSE 8000

CMD ["uvicorn", "coordinator.main:app", "--host", "0.0.0.0", "--port", "8000"]
