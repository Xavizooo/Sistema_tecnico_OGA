(() => {
    "use strict";

    const normalizeText = (value) => {
        return String(value ?? "")
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "")
            .toLowerCase()
            .trim();
    };

    const isListaClientes = () => {
        const path = window.location.pathname.toLowerCase();
        const params = new URLSearchParams(window.location.search);

        if (!path.includes("cliente")) {
            return false;
        }

        const view = params.get("view");

        return !view || view === "lista";
    };

    const findSearchInput = () => {
        const selectors = [
            "#clienteSearch",
            "#clientesSearch",
            "#searchClientes",
            "#searchClient",
            "#buscadorClientes",
            "#buscarClientes",
            "input[name='search']",
            "input[name='q']",
            "input[type='search']"
        ];

        for (const selector of selectors) {
            const element = document.querySelector(selector);

            if (element) {
                return element;
            }
        }

        const inputs = Array.from(
            document.querySelectorAll(
                "input[type='text'], input:not([type])"
            )
        );

        return inputs.find((input) => {
            const reference = normalizeText(
                [
                    input.id,
                    input.name,
                    input.className,
                    input.placeholder,
                    input.getAttribute("aria-label")
                ].join(" ")
            );

            return (
                reference.includes("buscar") ||
                reference.includes("search") ||
                reference.includes("cliente") ||
                reference.includes("filtro")
            );
        }) || null;
    };

    const findClientTable = (searchInput) => {
        const selectors = [
            "#clientesTable",
            "#tablaClientes",
            ".clientes-table",
            "table[data-clientes]",
            "table"
        ];

        let container = null;

        if (searchInput) {
            container =
                searchInput.closest(".card") ||
                searchInput.closest(".panel") ||
                searchInput.closest(".content") ||
                searchInput.parentElement;
        }

        if (container) {
            for (const selector of selectors) {
                const table = container.querySelector(selector);

                if (
                    table &&
                    table.querySelector("tbody") &&
                    table.querySelectorAll("tbody tr").length
                ) {
                    return table;
                }
            }
        }

        const tables = Array.from(document.querySelectorAll("table"));

        return tables.find((table) => {
            const text = normalizeText(table.textContent);

            return (
                table.querySelector("tbody") &&
                (
                    text.includes("cliente") ||
                    text.includes("nit") ||
                    text.includes("contacto") ||
                    text.includes("correo")
                )
            );
        }) || null;
    };

    const ensureEmptyRow = (tbody, table) => {
        let row = tbody.querySelector(
            "tr[data-clientes-search-empty='1']"
        );

        if (row) {
            return row;
        }

        row = document.createElement("tr");
        row.dataset.clientesSearchEmpty = "1";
        row.style.display = "none";

        const cell = document.createElement("td");

        const columnCount =
            table.querySelectorAll("thead th").length || 1;

        cell.colSpan = columnCount;
        cell.textContent = "No se encontraron clientes";
        cell.style.textAlign = "center";
        cell.style.padding = "28px 16px";
        cell.style.opacity = "0.65";
        cell.style.fontWeight = "600";

        row.appendChild(cell);
        tbody.appendChild(row);

        return row;
    };

    const initReactiveSearch = () => {
        if (!isListaClientes()) {
            return;
        }

        const searchInput = findSearchInput();

        if (!searchInput) {
            console.warn(
                "[Clientes] No se encontró el campo de búsqueda."
            );
            return;
        }

        if (searchInput.dataset.reactiveSearchReady === "1") {
            return;
        }

        const table = findClientTable(searchInput);

        if (!table) {
            console.warn(
                "[Clientes] No se encontró la tabla de clientes."
            );
            return;
        }

        const tbody = table.querySelector("tbody");

        if (!tbody) {
            return;
        }

        searchInput.dataset.reactiveSearchReady = "1";
        searchInput.autocomplete = "off";

        let animationFrame = null;

        const filterRows = () => {
            const query = normalizeText(searchInput.value);

            const rows = Array.from(
                tbody.querySelectorAll("tr")
            ).filter(
                (row) =>
                    row.dataset.clientesSearchEmpty !== "1"
            );

            let visibleCount = 0;

            rows.forEach((row) => {
                const rowText = normalizeText(
                    row.textContent
                );

                const visible =
                    query === "" ||
                    rowText.includes(query);

                row.style.display = visible ? "" : "none";

                if (visible) {
                    visibleCount += 1;
                }
            });

            const emptyRow = ensureEmptyRow(
                tbody,
                table
            );

            emptyRow.style.display =
                query !== "" && visibleCount === 0
                    ? ""
                    : "none";
        };

        const scheduleFilter = () => {
            if (animationFrame) {
                cancelAnimationFrame(
                    animationFrame
                );
            }

            animationFrame =
                requestAnimationFrame(() => {
                    filterRows();
                    animationFrame = null;
                });
        };

        /*
         * IMPORTANTE:
         * "input" se dispara con cada carácter,
         * pegado de texto y también al borrar.
         */
        searchInput.addEventListener(
            "input",
            scheduleFilter
        );

        /*
         * Evita que un formulario antiguo
         * recargue la página al presionar Enter.
         */
        const form = searchInput.closest("form");

        if (form) {
            form.addEventListener(
                "submit",
                (event) => {
                    event.preventDefault();
                    filterRows();
                }
            );
        }

        /*
         * Si se agregan clientes dinámicamente
         * sin recargar la página, se vuelve
         * a aplicar automáticamente el filtro.
         */
        const observer = new MutationObserver(
            () => {
                scheduleFilter();
            }
        );

        observer.observe(tbody, {
            childList: true
        });

        filterRows();

        console.log(
            "[Clientes] Search reactivo activo."
        );
    };

    const boot = () => {
        initReactiveSearch();

        /*
         * Segundo intento por si la tabla
         * aparece después mediante JavaScript.
         */
        setTimeout(
            initReactiveSearch,
            300
        );

        setTimeout(
            initReactiveSearch,
            1000
        );
    };

    if (
        document.readyState === "loading"
    ) {
        document.addEventListener(
            "DOMContentLoaded",
            boot
        );
    } else {
        boot();
    }
})();