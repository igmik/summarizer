# **SUMMARIZER**.
A summarizer telegram bot that will find a YouTube link and ask ChatGPT to summarize the content of it.
```sh
1. Задача: определить насколько радиус металлического диска одного колеса больше радиуса шины другого колеса.
2. В данном случае необходимо сравнивать высоту шины, а не диаметр металлического диска.
3. Чтобы найти высоту шины, используется формула: высота = 60% от ширины шины.
4. Высота шины одного колеса оказалась больше, чем у другого на 2,75 мм.
5. Решение задачи можно провести устно или путем умножения и вычитания чисел.

С вас 1 руб.
```

## Usage
Bot should be launched in the command line mode or in Docker container (recommended).
```sh
docker run --rm -e TELEGRAM_API_TOKEN=[TELEGRAM_API_TOKEN] -e OPENAI_API_KEY=[OPENAI_API_TOKEN] -d summarizer telegram_bot.py --config config.yml
```
Provide your personal TELEGRAM_API_TOKEN and OPENAI_AIP_TOKEN in the corresponding env vars.
Provide a config file containing whitelist for authorized telegram chat ID.

### TODO
Add separate caching for individual chat ID for seen YouTube links in Summarizer

### TODO
Allow adding chat ID in real time without bot restart
