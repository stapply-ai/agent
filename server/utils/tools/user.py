from browser_use import Tools, ActionResult, Browser

tools = Tools()


# TODO: later send a message on slack / telegram / email to the user 
@tools.action('Ask user for help with a question')
def ask_user(question: str, browser: Browser) -> ActionResult:
    answer = input(f'{question} > ')
    return f'The user responded with: {answer}'