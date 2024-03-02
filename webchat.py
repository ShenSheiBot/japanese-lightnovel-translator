import random
import time
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from abc import ABC, abstractmethod
from selenium.common.exceptions import ElementClickInterceptedException
from selenium.common.exceptions import ElementNotInteractableException, NoSuchElementException
from selenium.webdriver.common.keys import Keys
import pyperclip as pc
from utils import load_config
from gclient import get_service, check_latest_email
from loguru import logger
import re

total_count = 0


class WebChatApp(ABC):

    def __init__(self, dryrun=False):
        self.dryrun = dryrun
        self.total_count = 0
        self.config = load_config()
        if not dryrun:
            options = uc.ChromeOptions()
            options.add_argument("--load-extension=" + self.config["EXTENSION_FOLDER"])
            self.driver = uc.Chrome(options=options, use_subprocess=True, version_main=119)
        else:
            self.driver = None
            
    @abstractmethod
    def in_new_chat(self):
        pass
    
    @abstractmethod
    def delete_current_chat(self):
        pass
    
    @abstractmethod
    def create_new_chat(self):
        pass
    
    @abstractmethod
    def remove_popup(self):
        pass
    
    @abstractmethod
    def input_box(self):
        pass
    
    @abstractmethod
    def select_bot(self, name=None):
        pass
    
    @abstractmethod
    def select_reply(self):
        pass
    
    @abstractmethod
    def have_captcha(self):
        pass
    
    @abstractmethod
    def get_replies(self):
        pass
    
    @abstractmethod
    def stop_reply(self):
        pass
    
    @abstractmethod
    ## Handle to continue reply / force stop reply
    def handle_reply(self):
        pass
    
    def count_replies(self):
        return len(self.get_replies())
    
    def get_last_reply(self):
        if self.get_replies()[-1].startswith("Unable to reach Poe"):
            self.random_sleep(self.config["ANTI_BOT_DETECT_MIN_SLEEP"], self.config["ANTI_BOT_DETECT_MAX_SLEEP"])
            self.driver.refresh()
        return self.get_replies()[-1]
        
    def random_sleep(self, a=None, b=None):
        if self.dryrun:
            return
        if a is None:
            a = random.uniform(.5, 1.5)
        if b is None:
            b = random.uniform(2.5, 3.5)
        sleep_time_1 = random.uniform(a, b)
        sleep_time_2 = random.uniform(a, b)
        sleep_time = max(sleep_time_1, sleep_time_2)
        time.sleep(sleep_time)
        return sleep_time

    ## Click newchat, or delete current chat
    def newchat(self, name=None):
        if self.dryrun:
            return
            
        if self.total_count >= self.config["CHAT_COUNT_LIMIT"]:
            raise "Chat limit reached"
        
        if self.in_new_chat():
            if name is not None:
                self.select_bot(name)
            return
        else:
            self.random_sleep()
            try:
                self.delete_current_chat()
                if not self.in_new_chat():
                    self.create_new_chat()
            except ElementClickInterceptedException:            
                self.create_new_chat()
        self.select_bot(name)

    ## Type something and send
    def comm(self, text):
        self.total_count += 1
        self.remove_popup()
        self.random_sleep()
        num_replies = self.count_replies()
            
        # Type
        try:
            input_box = self.input_box()
        except NoSuchElementException:
            time.sleep(10)
            self.driver.refresh()
            input_box = self.input_box()
        pc.copy(re.sub(r'\n{3,}', '\n\n---\n\n', text))
        while True:
            try:
                input_box.send_keys(Keys.CONTROL, 'v')
                input_box.send_keys('\n')
                break
            except ElementNotInteractableException:
                time.sleep(10)
        
        # Wait after click send
        time.sleep(self.config["SEND_WAIT"])
        
        # Get reply
        flag = True
        new_num_replies = self.count_replies()

        while new_num_replies == num_replies:

            time.sleep(3.)
            # Wait until captcha is solved
            new_num_replies = self.count_replies()
            
            # Handle no captcha, no reply situation
            if not self.have_captcha():
                if flag:
                    try:
                        self.stop_reply()
                    except (IndexError, ElementClickInterceptedException):
                        continue
                    time.sleep(20.)
                    flag = False
                    new_num_replies = self.count_replies()
                else:
                    self.newchat()
                    global total_count
                    if total_count < self.config["RETRY_COUNT"]:
                        logger.critical("Response halting. Retrying...")
                        total_count += 1
                        return self.comm(text)
                    else:
                        total_count = 0
                        return ""
        
        reply = self.get_last_reply()
        
        self.total_time = 0.
        count = 0
        while True:
            time.sleep(3.)

            self.select_reply()
            new_reply = self.get_last_reply()
            
            if reply == new_reply:
                if reply.strip().endswith("aiting..."):
                    count += 1
                    if count >= 5:
                        self.driver.refresh()
                        self.random_sleep()
                    if count >= 10:
                        break
                    continue
                result = self.handle_reply()
                if result is None:
                    break
                else:
                    reply = result
            else:
                reply = new_reply
        
        if self.count_replies() >= self.config["NEW_CHAT_COUNT"]:
            self.newchat()

        # Random sleep to prevent bot detection
        self.random_sleep(self.config["ANTI_BOT_DETECT_MIN_SLEEP"], self.config["ANTI_BOT_DETECT_MAX_SLEEP"])
        
        return reply


class PoeChatApp(WebChatApp):
    def __init__(self, dryrun=False):
        super().__init__(dryrun)
        
        if not dryrun:
            # Manual login
            self.driver.get("https://www.poe.com/")
            self.random_sleep()
            self.driver.find_element(By.CSS_SELECTOR, 'input').send_keys(self.config["USERNAME"])
            self.random_sleep()
            self.driver.find_element(By.CSS_SELECTOR, 'button[class*=Button_primary]').click()
            try:
                service = get_service()
                total_time = 0.
                while total_time < 60.:
                    total_time += self.random_sleep()
                    email_content = check_latest_email(service, "noreply@poe.com")
                    if email_content is not None:
                        email_content = email_content.strip()
                        self.driver.find_element(By.CSS_SELECTOR, 'input').send_keys(email_content)
                        self.random_sleep()
                        self.driver.find_elements(By.CSS_SELECTOR, 'button[class*=Button_primary]')[0].click()
                        break
            except Exception as e:
                logger.error(e)
                logger.error("Google account invalid.")
                self.random_sleep(60, 60)
        self.random_sleep()
        self.select_bot()
                    
    def in_new_chat(self):
        msgs = self.driver.find_elements(By.CSS_SELECTOR, 'div[class*="messagePair"]')
        return len(msgs) == 0

    def delete_current_chat(self):
        # try:
        #     self.driver.find_element(By.CSS_SELECTOR, 'button[class*="ToggleSidebar"]').click()
        #     self.random_sleep()
        # except:
        #     pass
        try:
            self.driver.find_element(By.CSS_SELECTOR, 'button[class*=ChatHistory]').click()
            self.random_sleep()
            self.driver.find_element(By.CSS_SELECTOR, 'button[class*=Dropdown]').click()
            self.random_sleep()
            self.driver.find_element(By.CSS_SELECTOR, 'button[class*=danger]').click()
            self.random_sleep()
        except NoSuchElementException:
            return
        
    def create_new_chat(self):
        self.driver.get("https://www.poe.com/")
        self.random_sleep()
        
    def remove_popup(self):
        pass
    
    def select_reply(self):
        pass
    
    def select_bot(self, name=None):
        if self.dryrun:
            return
        if name is None:
            name = self.config["TRANSLATION_BOT_NAME"]
        sleep_count = 0
        more_button = self.driver.find_elements(By.CSS_SELECTOR, 'div[class*=BotSelectorHomeMain] button:last-of-type')
        while len(more_button) == 0:
            sleep_count += self.random_sleep()
            if sleep_count > self.config["BOT_SELECT_TIMEOUT"]:
                self.driver.refresh()
                sleep_count = 0
            more_button = self.driver.find_elements(By.CSS_SELECTOR, 
                                                    'div[class*=BotSelectorHomeMain] button:last-of-type')
        more_button = more_button[0]
        more_button.click()
        self.random_sleep()
        bot_buttons = self.driver.find_elements(By.CSS_SELECTOR, 'div[class*=BotHeader_textContainer]')
        while len(bot_buttons) == 0:
            self.random_sleep()
            bot_buttons = self.driver.find_elements(By.CSS_SELECTOR, 'div[class*=BotHeader_textContainer]')
        for button in bot_buttons:
            if button.text == name or ("Subscription access" in button.text and button.text[:-19].strip() == name):
                button.click()
                break
        self.random_sleep()
    
    def get_replies(self):
        self.random_sleep(.1, .5)
        pairs = self.driver.find_elements(By.CSS_SELECTOR, 'div[class*="messagePair"]')
        try:
            replies = [pair.children()[1].children()[1].get_attribute('textContent') for pair in pairs 
                       if len(pair.children()) > 1 and len(pair.children()[1].children()) > 1]
        except IndexError:
            return self.get_replies()
        return replies
    
    def input_box(self):
        return self.driver.find_element(By.CSS_SELECTOR, 'textarea')

    def have_captcha(self):
        return len(self.driver.find_elements(By.CSS_SELECTOR, 'button[class*="Stop"]')) > 0
   
    def stop_reply(self):
        pass
    
    def handle_reply(self):
        return None
    
    
class OpenAIChatApp(WebChatApp):
    
    def __init__(self, dryrun=False):
        super().__init__(dryrun)
        
        if not dryrun:
            # Manual login
            self.driver.get("https://chat.openai.com/")
            self.random_sleep()
            self.driver.find_element(By.CSS_SELECTOR, 'button').click()
            self.random_sleep()
            self.driver.find_element(By.CSS_SELECTOR, '#username.input').send_keys(self.config["USERNAME"])
            self.driver.find_element(By.CSS_SELECTOR, 'button').click()
            self.random_sleep()
            self.driver.find_element(By.CSS_SELECTOR, '#password').send_keys(self.config["PASSWORD"])
            self.driver.find_elements(By.CSS_SELECTOR, 'button')[2].click()
            
        # Click understand
        self.random_sleep()
        try:
            understand_button = self.driver.find_elements(By.CSS_SELECTOR, 'button.btn-primary')[1]
            understand_button.click()
        except IndexError:
            pass
        self.random_sleep()
                
        ## Disable censorship
        if not dryrun:
            self.driver.execute_script(open("resource/moderationv2.js", "r", encoding="utf-8").read())
        self.random_sleep()
        
    def select_bot(self, name=None):
        pass
    
    def in_new_chat(self):
        return len(self.driver.find_elements(By.CSS_SELECTOR, '.bg-yellow-200')) > 0
    
    def delete_current_chat(self):
        self.driver.find_elements(By.CSS_SELECTOR, 'button.p-1')[1].click()
        self.random_sleep()
        self.driver.find_element(By.CSS_SELECTOR, '.btn-danger').click()
        
    def create_new_chat(self):
        new_chat_button = self.driver.find_elements(By.CSS_SELECTOR, '.cursor-pointer')
        for button in new_chat_button:
            if button.text == "New chat":
                new_chat_button = button
                break
        new_chat_button.click()
        
    def remove_popup(self):
        for cross in self.driver.find_elements(By.CSS_SELECTOR, 'button.opacity-70'):
            cross.click()
    
    def select_reply(self):
        selections = self.driver.find_elements(By.CSS_SELECTOR, 'button.rounded-lg')
        if len(selections) == 2:
            selections[random.randint(0, 1)].click()
            
    def get_replies(self):
        return [prose.text for prose in self.driver.find_elements(By.CSS_SELECTOR, '.prose')]
    
    def input_box(self):
        return self.driver.find_element(By.CSS_SELECTOR, 'textarea')
            
    def have_captcha(self):
        return len(self.driver.find_elements(By.CSS_SELECTOR, '.box.container')) > 0

    def stop_reply(self):
        stop_button = self.driver.find_elements(By.CSS_SELECTOR, '.btn-neutral')
        stop_button[0].click()
        
    def handle_reply(self):
        continue_button = self.driver.find_elements(By.CSS_SELECTOR, '.btn-neutral')
        if len(continue_button) > 0 and "Continue" in continue_button[0].text:
            self.random_sleep()
            continue_button[0].click()
            time.sleep(3.)
            reply = self.driver.find_elements(By.CSS_SELECTOR, '.prose')[-1].text
            return reply
        elif len(continue_button) > 0 and "Regenerate" in continue_button[0].text:
            return None
        else:
            self.total_time += 3.
            if self.total_time > 60.:
                return None
