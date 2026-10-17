"""Prévia visual isolada. Não inicia servidor, microfone, modelos ou ferramentas."""
import math
import random
import tkinter as tk


class MatrixPreview:
    def __init__(self, root=None):
        self.root = root or tk.Tk()
        self.root.title("J.A.R.V.I.S. — teste visual Matrix")
        self.root.geometry("440x650")
        self.root.configure(bg="#000000")
        self.root.resizable(False, False)
        self.theme = "matrix"
        self.state = "Pronto"
        self.frame = 0
        self.timer = None
        self.random = random.Random()
        self.positions = [self.random.randrange(-12, 1) for _ in range(24)]
        self.characters = "01ABCDEFGHIJKLMNOPQRSTUVWXYZ@#$*+-"

        tk.Label(self.root, text="J.A.R.V.I.S. // MATRIX", bg="#000000", fg="#00ff41",
                 font=("Consolas", 19, "bold")).pack(pady=(15,4))
        tk.Label(self.root, text="PRÉVIA VISUAL • NÃO EXECUTA COMANDOS", bg="#000000", fg="#7bb88a",
                 font=("Segoe UI",9)).pack(pady=(0,6))
        self.canvas = tk.Canvas(self.root,width=408,height=200,bg="#000000",highlightthickness=1,
                                highlightbackground="#174d2b")
        self.canvas.pack(padx=15,pady=8)
        self.cells=[]
        for column in range(24):
            self.cells.append([self.canvas.create_text(12+column*16,10+row*15,
                text=self.random.choice(self.characters),fill="#000000",font=("Consolas",12,"bold"))
                for row in range(13)])
        self.orb=self.canvas.create_oval(130,28,278,176,fill="#1b7fa8",outline="#38e1ff",width=2,state="hidden")
        self.status = tk.Label(self.root,text="[ PRONTO ]",fg="#00ff41",bg="#000000",font=("Consolas",14,"bold"))
        self.status.pack(pady=(3,8))

        selector=tk.Frame(self.root,bg="#000000");selector.pack(fill="x",padx=16)
        for label,theme in (("Testar Matrix","matrix"),("Comparar círculo azul","orb")):
            tk.Button(selector,text=label,command=lambda value=theme:self.set_theme(value),
                      bg="#06140b",fg="#00ff41",activebackground="#123c22",activeforeground="#ffffff",
                      relief="solid",bd=1,padx=8,pady=7).pack(side="left",expand=True,fill="x",padx=3)
        states=tk.Frame(self.root,bg="#000000");states.pack(fill="x",padx=16,pady=9)
        for state in ("Pronto","Ouvindo","Pensando","Falando"):
            tk.Button(states,text=state,command=lambda value=state:self.set_state(value),
                      bg="#000000",fg="#8aeaa0",activebackground="#174d2b",relief="flat",
                      font=("Segoe UI",9)).pack(side="left",expand=True,fill="x")

        terminal=tk.Text(self.root,height=6,bg="#030b05",fg="#78e892",relief="solid",bd=1,
                         font=("Consolas",11),wrap="word",padx=10,pady=8)
        terminal.pack(fill="both",expand=True,padx=18,pady=(0,10))
        terminal.insert("end","> Visual de demonstração\n\nJarvis: Estou aqui. Pode falar.\n\nOs estados acima são simulados. A interface e as configurações atuais foram preservadas.")
        terminal.configure(state="disabled")
        controls=tk.Frame(self.root,bg="#000000");controls.pack(fill="x",padx=18)
        for title in ("Ativar escuta","Interromper"):
            tk.Button(controls,text=title,state="disabled",disabledforeground="#63816b",
                      bg="#07140b",relief="solid",bd=1,pady=7).pack(side="left",expand=True,fill="x",padx=3)
        tk.Label(self.root,text="Controles de voz desativados nesta prévia.",bg="#000000",fg="#7bb88a",
                 font=("Segoe UI",9)).pack(pady=(6,4))
        tk.Button(self.root,text="Fechar prévia — manter visual atual",command=self.close,
                  bg="#102818",fg="#d9ffe1",relief="flat",pady=7).pack(fill="x",padx=20,pady=(3,14))
        self.root.protocol("WM_DELETE_WINDOW",self.close)
        self.root.bind("<Escape>",lambda event:self.close())
        self.animate()

    def set_theme(self,theme):
        self.theme=theme
        for column in self.cells:
            for item in column:
                self.canvas.itemconfigure(item,state="normal" if theme=="matrix" else "hidden")
        self.canvas.itemconfigure(self.orb,state="normal" if theme=="orb" else "hidden")

    def set_state(self,state):
        self.state=state
        colors={"Pronto":"#00ff41","Ouvindo":"#aeffc2","Pensando":"#ffd35b","Falando":"#47f7b4"}
        self.status.configure(text=f"[ {state.upper()} ]",fg=colors[state])

    def animate(self):
        self.frame+=1
        if self.theme=="matrix":
            for column,items in enumerate(self.cells):
                if self.frame % (2 if self.state=="Pronto" else 1)==0:
                    self.positions[column]=(self.positions[column]+1)%22
                head=self.positions[column]
                for row,item in enumerate(items):
                    delta=head-row
                    color="#ddffe5" if delta==0 else "#00ff41" if delta==1 else "#00952a" if 1<delta<4 else "#003b15" if 4<=delta<7 else "#000000"
                    self.canvas.itemconfigure(item,fill=color)
                    if self.random.random()<0.06:
                        self.canvas.itemconfigure(item,text=self.random.choice(self.characters))
        else:
            pulse=(math.sin(self.frame*0.2)+1)/2
            growth=4+pulse*(12 if self.state!="Pronto" else 6)
            self.canvas.coords(self.orb,130-growth,28-growth,278+growth,176+growth)
        self.timer=self.root.after(140,self.animate)

    def close(self):
        if self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer=None
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    MatrixPreview().run()


if __name__=="__main__":
    main()
