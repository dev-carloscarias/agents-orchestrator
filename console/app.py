from harness.budget import BudgetManager
from console.menus.main_menu import MainMenu


class ConsoleApp:
    def __init__(self) -> None:
        import main as main_mod

        self.config = main_mod.load_config()
        self.budget = BudgetManager()
        self.menu = MainMenu(self.config, self.budget)

    def run(self) -> None:
        self.menu.run()
