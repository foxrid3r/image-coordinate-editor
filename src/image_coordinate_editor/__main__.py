import tkinter as tk

from .app import PngCoordinateEditor


def main() -> None:
    root = tk.Tk()
    PngCoordinateEditor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
