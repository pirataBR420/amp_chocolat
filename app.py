
from flask import Flask, render_template, request, redirect, url_for
import sqlite3
from datetime import datetime, timedelta

app = Flask(__name__)
DATABASE = "inventario.db"


def conectar_db():
    conexion = sqlite3.connect(DATABASE)
    conexion.row_factory = sqlite3.Row
    return conexion


def crear_tablas():
    conexion = conectar_db()
    # Agregar el mínimo de existencias si todavía no existe
    columnas = conexion.execute(
        "PRAGMA table_info(ingredientes)"
    ).fetchall()

    nombres_columnas = [columna["name"] for columna in columnas]

    if "minimo" not in nombres_columnas:
        conexion.execute(
            "ALTER TABLE ingredientes "
            "ADD COLUMN minimo REAL NOT NULL DEFAULT 0"
        )
    # Conservamos la tabla de materias primas que ya teníamos.
    conexion.execute("""
        CREATE TABLE IF NOT EXISTS ingredientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            cantidad REAL NOT NULL,
            unidad TEXT NOT NULL
        )
    """)

    # Preparaciones elaboradas que quedan disponibles para uso posterior.
    conexion.execute("""
        CREATE TABLE IF NOT EXISTS preparaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            cantidad REAL NOT NULL,
            unidad TEXT NOT NULL,
            fecha_elaboracion TEXT NOT NULL,
            fecha_limite TEXT NOT NULL,
            estado TEXT NOT NULL DEFAULT 'Disponible'
        )
    """)

    conexion.commit()
    conexion.close()
    


@app.route("/")
def inicio():
    conexion = conectar_db()
    total_ingredientes = conexion.execute(
        "SELECT COUNT(*) FROM ingredientes"
    ).fetchone()[0]
    total_preparaciones = conexion.execute(
        "SELECT COUNT(*) FROM preparaciones WHERE estado = 'Disponible'"
    ).fetchone()[0]
    conexion.close()

    return render_template(
        "inicio.html",
        total_ingredientes=total_ingredientes,
        total_preparaciones=total_preparaciones
    )


@app.route("/almacenamiento")
def almacenamiento():
    return render_template("almacenamiento.html")


@app.route("/materias-primas")
def materias_primas():
    conexion = conectar_db()
    ingredientes = conexion.execute(
        "SELECT * FROM ingredientes ORDER BY nombre"
    ).fetchall()
    conexion.close()

    return render_template("index.html", ingredientes=ingredientes)


@app.route("/agregar", methods=["POST"])
def agregar():
    nombre = request.form.get("nombre", "").strip()
    cantidad_texto = request.form.get("cantidad", "").strip()
    unidad = request.form.get("unidad", "")

    if not nombre or unidad not in ("g", "ml"):
        return "Datos inválidos. Regresa e intenta de nuevo.", 400

    try:
        cantidad = float(cantidad_texto.replace(",", "."))
        if not 0 < cantidad <= 1000000000:
            raise ValueError
    except ValueError:
        return "La cantidad debe ser un número mayor que cero.", 400

    conexion = conectar_db()
    conexion.execute(
        """INSERT INTO ingredientes (nombre, cantidad, unidad)
           VALUES (?, ?, ?)""",
        (nombre, cantidad, unidad)
    )
    conexion.commit()
    conexion.close()

    return redirect(url_for("materias_primas"))



@app.route("/movimientos", methods=["GET", "POST"])
def movimientos():
    error = None
    exito = request.args.get("exito")

    if request.method == "POST":
        ingrediente_id = request.form.get("ingrediente_id", "")
        tipo = request.form.get("tipo", "")
        cantidad_texto = request.form.get("cantidad", "").strip()
        motivo = request.form.get("motivo", "").strip()

        if tipo not in ("Entrada", "Salida"):
            error = "Selecciona un tipo de movimiento."
        elif not motivo:
            error = "Selecciona el motivo del movimiento."
        else:
            try:
                cantidad = float(cantidad_texto.replace(",", "."))
                if not 0 < cantidad <= 1000000000:
                    raise ValueError
            except ValueError:
                cantidad = 0
                error = "Introduce una cantidad válida mayor que cero."

        if not error:
            conexion = conectar_db()

            try:
                conexion.execute("BEGIN IMMEDIATE")

                ingrediente = conexion.execute(
                    "SELECT * FROM ingredientes WHERE id = ?",
                    (ingrediente_id,)
                ).fetchone()

                if ingrediente is None:
                    error = "El ingrediente seleccionado no existe."

                elif tipo == "Salida" and cantidad > ingrediente["cantidad"]:
                    error = (
                        f"Existencias insuficientes. "
                        f"Disponible: {ingrediente['cantidad']} "
                        f"{ingrediente['unidad']}."
                    )

                else:
                    if tipo == "Entrada":
                        nueva_cantidad = ingrediente["cantidad"] + cantidad
                    else:
                        nueva_cantidad = ingrediente["cantidad"] - cantidad

                    conexion.execute(
                        "UPDATE ingredientes SET cantidad = ? WHERE id = ?",
                        (nueva_cantidad, ingrediente["id"])
                    )

                    conexion.execute(
                        """INSERT INTO movimientos
                           (tipo, producto, cantidad, unidad, motivo, fecha)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            tipo,
                            ingrediente["nombre"],
                            cantidad,
                            ingrediente["unidad"],
                            motivo,
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        )
                    )

                    conexion.commit()
                    conexion.close()

                    return redirect(
                        url_for("movimientos", exito="Movimiento registrado")
                    )

                conexion.rollback()

            except Exception:
                conexion.rollback()
                raise

            finally:
                conexion.close()

    conexion = conectar_db()

    ingredientes = conexion.execute(
        "SELECT * FROM ingredientes ORDER BY nombre"
    ).fetchall()

    historial = conexion.execute(
        "SELECT * FROM movimientos ORDER BY id DESC LIMIT 50"
    ).fetchall()

    conexion.close()

    return render_template(
        "movimientos.html",
        ingredientes=ingredientes,
        historial=historial,
        error=error,
        exito=exito
    )


@app.route("/actualizar-minimo", methods=["POST"])
def actualizar_minimo():
    ingrediente_id = request.form.get("ingrediente_id", "")
    minimo_texto = request.form.get("minimo", "").strip()

    try:
        minimo = float(minimo_texto.replace(",", "."))
        if not 0 <= minimo <= 1000000000:
            raise ValueError
    except ValueError:
        return redirect(url_for(
            "alertas",
            error="Introduce un mínimo válido."
        ))

    conexion = conectar_db()
    conexion.execute(
        "UPDATE ingredientes SET minimo = ? WHERE id = ?",
        (minimo, ingrediente_id)
    )
    conexion.commit()
    conexion.close()

    return redirect(url_for(
        "alertas",
        exito="Mínimo actualizado correctamente."
    ))



@app.route("/preparaciones-espera", methods=["GET", "POST"])
def preparaciones_espera():
    error = None
    exito = request.args.get("exito")

    if request.method == "POST":
        accion = request.form.get("accion", "")

        # REGISTRAR UNA PREPARACIÓN
        if accion == "registrar":
            nombre = request.form.get("nombre", "").strip()
            cantidad_texto = request.form.get("cantidad", "").strip()
            unidad = request.form.get("unidad", "")
            fecha_elaboracion = request.form.get("fecha_elaboracion", "")
            fecha_limite = request.form.get("fecha_limite", "")

            if not nombre:
                error = "Escribe el nombre de la preparación."
            elif unidad not in ("g", "ml"):
                error = "Selecciona una unidad válida."
            else:
                try:
                    cantidad = float(cantidad_texto.replace(",", "."))
                    if not 0 < cantidad <= 1000000000:
                        raise ValueError

                    elaboracion = datetime.strptime(
                        fecha_elaboracion, "%Y-%m-%d"
                    ).date()
                    limite = datetime.strptime(
                        fecha_limite, "%Y-%m-%d"
                    ).date()

                    if limite < elaboracion:
                        error = (
                            "La fecha límite no puede ser anterior "
                            "a la fecha de elaboración."
                        )
                except ValueError:
                    error = (
                        "Revisa la cantidad y las fechas. "
                        "La cantidad debe ser mayor que cero."
                    )

            if not error:
                conexion = conectar_db()
                try:
                    conexion.execute(
                        """INSERT INTO preparaciones
                           (nombre, cantidad, unidad, fecha_elaboracion,
                            fecha_limite, estado)
                           VALUES (?, ?, ?, ?, ?, 'Disponible')""",
                        (
                            nombre, cantidad, unidad,
                            fecha_elaboracion, fecha_limite
                        )
                    )
                    conexion.commit()
                finally:
                    conexion.close()

                return redirect(url_for(
                    "preparaciones_espera",
                    exito="Preparación registrada correctamente"
                ))

        # REGISTRAR CONSUMO
        elif accion == "consumir":
            preparacion_id = request.form.get("preparacion_id", "")
            cantidad_texto = request.form.get("cantidad_consumida", "").strip()
            motivo = request.form.get("motivo", "")

            if motivo not in ("Producción", "Deterioro", "Vencimiento", "Otro"):
                error = "Selecciona un motivo válido."
            else:
                try:
                    cantidad = float(cantidad_texto.replace(",", "."))
                    if not 0 < cantidad <= 1000000000:
                        raise ValueError
                except ValueError:
                    cantidad = 0
                    error = "La cantidad debe ser un número mayor que cero."

            if not error:
                conexion = conectar_db()
                try:
                    conexion.execute("BEGIN IMMEDIATE")

                    preparacion = conexion.execute(
                        """SELECT * FROM preparaciones
                           WHERE id = ?""",
                        (preparacion_id,)
                    ).fetchone()

                    if preparacion is None:
                        error = "No se encontró esa preparación."
                    elif preparacion["estado"] != "Disponible":
                        error = "Esa preparación ya no está disponible."
                    elif cantidad > preparacion["cantidad"]:
                        error = (
                            f"Existencias insuficientes. "
                            f"Disponible: {preparacion['cantidad']} "
                            f"{preparacion['unidad']}."
                        )

                    if error:
                        conexion.rollback()
                    else:
                        restante = round(
                            preparacion["cantidad"] - cantidad, 6
                        )

                        if restante <= 0:
                            restante = 0
                            estado = "Agotada"
                        else:
                            estado = "Disponible"

                        conexion.execute(
                            """UPDATE preparaciones
                               SET cantidad = ?, estado = ?
                               WHERE id = ?""",
                            (restante, estado, preparacion["id"])
                        )

                        conexion.execute(
                            """INSERT INTO movimientos
                               (tipo, producto, cantidad, unidad, motivo, fecha)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (
                                "Consumo de preparación",
                                preparacion["nombre"],
                                cantidad,
                                preparacion["unidad"],
                                motivo,
                                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            )
                        )
                        conexion.commit()

                        return redirect(url_for(
                            "preparaciones_espera",
                            exito="Consumo registrado correctamente"
                        ))
                finally:
                    conexion.close()
        else:
            error = "Acción no válida."

    conexion = conectar_db()
    preparaciones = conexion.execute(
        """SELECT * FROM preparaciones
           ORDER BY fecha_limite ASC, nombre ASC"""
    ).fetchall()
    conexion.close()

    return render_template(
        "preparaciones.html",
        preparaciones=preparaciones,
        error=error,
        exito=exito,
        hoy=datetime.now().strftime("%Y-%m-%d")
    )





@app.route("/alertas")
def alertas():
    conexion = conectar_db()

    ingredientes_bajos = conexion.execute(
        """SELECT * FROM ingredientes
           WHERE minimo > 0 AND cantidad <= minimo
           ORDER BY nombre"""
    ).fetchall()

    ingredientes = conexion.execute(
        "SELECT * FROM ingredientes ORDER BY nombre"
    ).fetchall()

    hoy = datetime.now().date()
    fecha_aviso = hoy + timedelta(days=7)

    preparaciones_vencidas = conexion.execute(
        """SELECT * FROM preparaciones
           WHERE estado = 'Disponible'
           AND fecha_limite < ?
           ORDER BY fecha_limite"""
        ,
        (hoy.strftime("%Y-%m-%d"),)
    ).fetchall()

    preparaciones_por_vencer = conexion.execute(
        """SELECT * FROM preparaciones
           WHERE estado = 'Disponible'
           AND fecha_limite >= ?
           AND fecha_limite <= ?
           ORDER BY fecha_limite"""
        ,
        (
            hoy.strftime("%Y-%m-%d"),
            fecha_aviso.strftime("%Y-%m-%d")
        )
    ).fetchall()

    conexion.close()

    return render_template(
        "alertas.html",
        ingredientes_bajos=ingredientes_bajos,
        ingredientes=ingredientes,
        preparaciones_vencidas=preparaciones_vencidas,
        preparaciones_por_vencer=preparaciones_por_vencer,
        exito=request.args.get("exito"),
        error=request.args.get("error"),
        hoy=hoy.strftime("%Y-%m-%d")
    )


@app.route("/historial")
def historial():
    fecha_desde = request.args.get("fecha_desde", "").strip()
    fecha_hasta = request.args.get("fecha_hasta", "").strip()
    tipo = request.args.get("tipo", "").strip()
    producto = request.args.get("producto", "").strip()
    motivo = request.args.get("motivo", "").strip()

    condiciones = []
    parametros = []

    if fecha_desde:
        condiciones.append("date(fecha) >= date(?)")
        parametros.append(fecha_desde)

    if fecha_hasta:
        condiciones.append("date(fecha) <= date(?)")
        parametros.append(fecha_hasta)

    if tipo:
        condiciones.append("tipo = ?")
        parametros.append(tipo)

    if producto:
        condiciones.append("producto LIKE ?")
        parametros.append(f"%{producto}%")

    if motivo:
        condiciones.append("motivo LIKE ?")
        parametros.append(f"%{motivo}%")

    consulta = "SELECT * FROM movimientos"

    if condiciones:
        consulta += " WHERE " + " AND ".join(condiciones)

    consulta += " ORDER BY fecha DESC, id DESC"

    conexion = conectar_db()
    movimientos = conexion.execute(
        consulta, parametros
    ).fetchall()
    conexion.close()

    return render_template(
        "historial.html",
        movimientos=movimientos,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        tipo=tipo,
        producto=producto,
        motivo=motivo
    )

crear_tablas()

if __name__ == "__main__":
    app.run(debug=True)
