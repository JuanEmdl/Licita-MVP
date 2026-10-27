from src.shared.schemas.domain import CategoriaRequisito as C, EstadoDictamen as E
from src.worker_analysis.scoring.motor import MotorPuntaje
from tests.conftest import dic, req


def test_puntaje_perfecto():
    """Valida matemáticamente que al cumplir todos los requisitos de todas las categorías el puntaje es 100."""
    requisitos = [req("T1", C.TECNICO), req("E1", C.EXPERIENCIA), req("F1", C.FINANCIERO),
                  req("J1", C.JURIDICO), req("P1", C.PERSONAL)]
    dictamenes = [dic(r.identificador, E.CUMPLE) for r in requisitos]

    resultado = MotorPuntaje().calcular(requisitos, dictamenes)

    assert resultado.puntaje_total == 100.0
    assert resultado.aporte_por_categoria[C.TECNICO] == 40.0
    assert resultado.aporte_por_categoria[C.EXPERIENCIA] == 30.0
    assert resultado.categorias_no_aplicables == []
    assert resultado.con_evidencia


def test_cumplimiento_parcial_redistribuye_categorias_ausentes():
    """Solo hay técnicos: el técnico pesa 100 y 1.5/2 cumplido da 75."""
    requisitos = [req("T1", C.TECNICO), req("T2", C.TECNICO)]
    dictamenes = [dic("T1", E.CUMPLE), dic("T2", E.CUMPLE_PARCIALMENTE)]

    resultado = MotorPuntaje().calcular(requisitos, dictamenes)

    assert resultado.peso_efectivo_por_categoria[C.TECNICO] == 100.0
    assert resultado.aporte_por_categoria[C.TECNICO] == 75.0
    assert resultado.puntaje_total == 75.0
    assert set(resultado.categorias_no_aplicables) == {C.EXPERIENCIA, C.FINANCIERO, C.JURIDICO, C.PERSONAL}


def test_categoria_ausente_no_regala_puntos():
    """HU-08 CA-02: una categoría ausente no reduce el puntaje, pero tampoco aporta puntos sin evidencia."""
    requisitos = [req("J1", C.JURIDICO)]
    dictamenes = [dic("J1", E.NO_CUMPLE)]

    resultado = MotorPuntaje().calcular(requisitos, dictamenes)

    # Antes daba 90: las categorías no evaluadas sumaban su peso completo.
    assert resultado.puntaje_total == 0.0
    assert resultado.aporte_por_categoria[C.FINANCIERO] == 0.0


def test_redistribucion_proporcional():
    """Técnico (40) y jurídico (10) presentes: pesan 80 y 20."""
    requisitos = [req("T1", C.TECNICO), req("J1", C.JURIDICO)]
    dictamenes = [dic("T1", E.CUMPLE), dic("J1", E.NO_CUMPLE)]

    resultado = MotorPuntaje().calcular(requisitos, dictamenes)

    assert resultado.peso_efectivo_por_categoria[C.TECNICO] == 80.0
    assert resultado.peso_efectivo_por_categoria[C.JURIDICO] == 20.0
    assert resultado.puntaje_total == 80.0


def test_sin_dictamenes_puntaje_cero_sin_evidencia():
    """Antes, sin requisitos aprobados el puntaje era 100 y la recomendación 'Ofertar'."""
    resultado = MotorPuntaje().calcular([], [])

    assert resultado.puntaje_total == 0.0
    assert not resultado.con_evidencia
    assert resultado.total_dictamenes == 0


def test_dictamen_huerfano_se_ignora():
    resultado = MotorPuntaje().calcular([req("T1", C.TECNICO)], [dic("T1", E.CUMPLE), dic("X9", E.NO_CUMPLE)])

    assert resultado.total_dictamenes == 1
    assert resultado.puntaje_total == 100.0
