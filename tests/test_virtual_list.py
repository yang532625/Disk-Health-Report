import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
import unittest

try:
    import tkinter as tk
    import customtkinter as ctk
    from virtual_list import VirtualList
    _TK_OK = True
except Exception:
    _TK_OK = False


@unittest.skipUnless(_TK_OK, "Tk/customtkinter no disponible")
class TestVirtualList(unittest.TestCase):
    def setUp(self):
        self.root = ctk.CTk()
        self.root.geometry("400x300")
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def _make_list(self, row_height=40):
        def build_row(parent):
            row = ctk.CTkFrame(parent)
            row._lbl = ctk.CTkLabel(row, text="")
            row._lbl.pack()
            return row

        def bind_row(row, index, item):
            row._lbl.configure(text=str(item))

        vl = VirtualList(self.root, row_height=row_height,
                         build_row=build_row, bind_row=bind_row)
        vl.pack(fill="both", expand=True)
        self.root.update_idletasks()
        self.root.update()
        return vl

    def test_pool_is_bounded(self):
        vl = self._make_list()
        vl.set_items(list(range(2000)))
        self.root.update_idletasks()
        self.root.update()
        # El pool debe ser muchÃ­simo menor que el total de elementos.
        self.assertLess(len(vl._pool), 200)
        self.assertGreater(len(vl._pool), 0)

    def test_scrollregion_matches_items(self):
        vl = self._make_list(row_height=40)
        vl.set_items(list(range(100)))
        self.root.update_idletasks()
        region = vl._canvas.cget("scrollregion").split()
        self.assertEqual(int(float(region[3])), 100 * 40)

    def test_empty_items_hides_rows(self):
        vl = self._make_list()
        vl.set_items(list(range(50)))
        self.root.update_idletasks()
        vl.set_items([])
        self.root.update_idletasks()
        for _widget, win_id in vl._pool:
            self.assertEqual(vl._canvas.itemcget(win_id, "state"), "hidden")


if __name__ == "__main__":
    unittest.main()
