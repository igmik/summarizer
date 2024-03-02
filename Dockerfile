FROM python:3.10.5-bullseye
RUN mkdir -p /python/summarizer
WORKDIR /python/summarizer
COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt
COPY src src

COPY patches/captions.py /usr/local/lib/python3.10/site-packages/pytube/captions.py
COPY patches/innertube.py /usr/local/lib/python3.10/site-packages/pytube/innertube.py

ENTRYPOINT ["python","-u"]