FROM python:3.10.5-bullseye
RUN mkdir -p /python/summarizer
WORKDIR /python/summarizer
COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt
COPY src src

ENTRYPOINT ["python","-u"]
