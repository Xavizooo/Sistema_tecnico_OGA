(function () {
  const paisSelect = document.getElementById('clientePais');
  const ciudadSelect = document.getElementById('clienteCiudad');
  const dataNode = document.getElementById('clientesPaisesData');

  if (!paisSelect || !ciudadSelect || !dataNode) return;

  let paises = {};
  try {
    paises = JSON.parse(dataNode.textContent || '{}');
  } catch (error) {
    console.error('No fue posible leer el catálogo de países y ciudades.', error);
    return;
  }

  function cargarCiudades() {
    const pais = paisSelect.value;
    const ciudadGuardada = ciudadSelect.dataset.selected || '';
    const ciudades = Array.isArray(paises[pais]) ? paises[pais] : [];

    ciudadSelect.innerHTML = '';

    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = pais ? 'Seleccione una ciudad' : 'Seleccione primero un país';
    ciudadSelect.appendChild(placeholder);

    ciudades.forEach(function (ciudad) {
      const option = document.createElement('option');
      option.value = ciudad;
      option.textContent = ciudad;
      if (ciudad === ciudadGuardada) option.selected = true;
      ciudadSelect.appendChild(option);
    });

    ciudadSelect.disabled = !pais;
    ciudadSelect.dataset.selected = '';
  }

  paisSelect.addEventListener('change', cargarCiudades);
  cargarCiudades();
})();
