import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
import math

def mostrar_campos(*args):
    limpiar_campos()
    frame_catetos.pack_forget()
    frame_hipotenusa.pack_forget()
    frame_resultado.pack_forget()
    resultado.set("")

    opcion = opcion_var.get()
    if opcion == "Dos catetos":
        frame_catetos.pack(padx=10, pady=5, fill="both")
        frame_resultado.pack(pady=10, padx=10, fill="both")
    elif opcion == "Un cateto y la hipotenusa":
        frame_hipotenusa.pack(padx=10, pady=5, fill="both")
        frame_resultado.pack(pady=10, padx=10, fill="both")

def calcular():
    opcion = opcion_var.get()

    try:
        if opcion == "Dos catetos":
            a = float(entrada_a.get())
            b = float(entrada_b.get())
            c = math.sqrt(a**2 + b**2)
            resultado.set(f"Hipotenusa: {c:.2f}")
        
        elif opcion == "Un cateto y la hipotenusa":
            cateto = float(entrada_cateto.get())
            hipotenusa = float(entrada_hipotenusa.get())

            if hipotenusa <= cateto:
                raise ValueError("La hipotenusa debe ser mayor que el cateto.")

            faltante = math.sqrt(hipotenusa**2 - cateto**2)
            resultado.set(f"Cateto faltante: {faltante:.2f}")
        
        else:
            resultado.set("Selecciona una opción válida.")
            return

        repetir = messagebox.askyesno("¿Otro cálculo?", "¿Quieres hacer otro cálculo?")
        if repetir:
            limpiar_campos()
            opcion_var.set("Selecciona una opción")
            frame_catetos.pack_forget()
            frame_hipotenusa.pack_forget()
            frame_resultado.pack_forget()
        else:
            ventana.destroy()

    except ValueError as e:
        messagebox.showerror("Error", str(e))

def limpiar_campos():
    entrada_a.delete(0, tk.END)
    entrada_b.delete(0, tk.END)
    entrada_cateto.delete(0, tk.END)
    entrada_hipotenusa.delete(0, tk.END)
    resultado.set("")

# Crear ventana
ventana = tk.Tk()
ventana.title("Calculadora de Pitágoras")
ventana.iconbitmap("triangulo.ico")
ventana.minsize(width=200, height=100)

# Variables
resultado = tk.StringVar()
opcion_var = tk.StringVar()

# Etiqueta y combobox
tk.Label(ventana, text="¿Qué datos tienes?").pack(pady=5)
combo = ttk.Combobox(ventana, textvariable=opcion_var, state="readonly")
combo['values'] = ("Dos catetos", "Un cateto y la hipotenusa")
combo.set("Selecciona una opción")
combo.pack()
combo.bind("<<ComboboxSelected>>", mostrar_campos)

# Frame para dos catetos
frame_catetos = tk.LabelFrame(ventana, text="Introduce los catetos")
tk.Label(frame_catetos, text="Cateto a:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
entrada_a = tk.Entry(frame_catetos)
entrada_a.grid(row=0, column=1, padx=5, pady=5)

tk.Label(frame_catetos, text="Cateto b:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
entrada_b = tk.Entry(frame_catetos)
entrada_b.grid(row=1, column=1, padx=5, pady=5)

btn_calcular_catetos = tk.Button(frame_catetos, text="Calcular", command=calcular)
btn_calcular_catetos.grid(row=2, column=0, columnspan=2, pady=10)

# Frame para un cateto y la hipotenusa
frame_hipotenusa = tk.LabelFrame(ventana, text="Introduce un cateto y la hipotenusa")
tk.Label(frame_hipotenusa, text="Cateto conocido:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
entrada_cateto = tk.Entry(frame_hipotenusa)
entrada_cateto.grid(row=0, column=1, padx=5, pady=5)

tk.Label(frame_hipotenusa, text="Hipotenusa:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
entrada_hipotenusa = tk.Entry(frame_hipotenusa)
entrada_hipotenusa.grid(row=1, column=1, padx=5, pady=5)

btn_calcular_hipotenusa = tk.Button(frame_hipotenusa, text="Calcular", command=calcular)
btn_calcular_hipotenusa.grid(row=2, column=0, columnspan=2, pady=10)

# Frame del resultado (solo se muestra si se elige opción)
frame_resultado = tk.LabelFrame(ventana, text="Resultado")
entrada_resultado = tk.Entry(frame_resultado, textvariable=resultado, font=("Arial", 12), state="readonly", justify="center")
entrada_resultado.pack(padx=10, pady=5, fill="x")

# Ejecutar aplicación
ventana.mainloop()
