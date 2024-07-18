FROM python:3.10.5-bullseye
RUN mkdir -p /python/summarizer
WORKDIR /python/summarizer
COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt
COPY src src

COPY patches/innertube.py /usr/local/lib/python3.10/site-packages/pytube/innertube.py
COPY patches/__main__.py /usr/local/lib/python3.10/site-packages/pytube/__main__.py

ENTRYPOINT ["python","-u"]
