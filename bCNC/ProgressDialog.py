import tkinter
from tkinter import ttk
import tkinter.dialog


class ProgressDialog(tkinter.Toplevel):
    def __init__(self, parent, text):
        super().__init__(parent)

        self.title("Progress Dialog")
        self.resizable(False, False)

        self.progress = tkinter.DoubleVar()

        # Parent geometry
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_w = parent.winfo_width()
        parent_h = parent.winfo_height()

        # Center coordinates
        x = parent_x + (parent_w - 300) // 2
        y = parent_y + (parent_h - 150) // 2

        self.geometry(f"300x150+{x}+{y}")

        self.cancelled = False

        # Keep the dialog associated with the parent
        self.transient(parent)

        # Make it modal
        self.grab_set()

        lineFrame = tkinter.Frame(self)
        lineFrame.pack(side='top', fill='x', expand=True)

        tkinter.Label(lineFrame, text=text).pack(side='left', fill='y', padx=5, pady=5, expand=False)
        self.progressLabel = tkinter.Label(lineFrame, text="0%")
        self.progressLabel.pack(side='left', fill='both', expand=True)

        # Dialog contents
        self.progressBar = ttk.Progressbar(
            self,
            length=100,
            maximum=100,
            mode="determinate",
            orient="horizontal",
            variable=self.progress
        )
        
        self.progressBar.pack(side='top', fill='x', padx=5, pady=5)

        # Buttons
        button_frame = tkinter.Frame(self)
        button_frame.pack(pady=25)

        tkinter.Button(
            button_frame,
            text="Cancel",
            command=self.cancel
        ).pack(side="left", padx=5)

    def cancel(self):
        self.cancelled = True

    def setProgress(self, value):
        self.progress.set(value)
        self.progressLabel.config(text=str(int(value * 10) / 10) + "%")


