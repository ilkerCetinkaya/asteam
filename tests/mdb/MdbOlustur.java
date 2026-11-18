// Test için .mdb (Access 2000 / Jet4) dosyası üretir. Jackcess kullanır.
// Kullanım: java -cp <jackcess jar'ları> MdbOlustur.java <cikti.mdb> <genis|uzun> < satirlar.tsv
// TSV satırı: id \t numune \t tarih(yyyy-MM-dd HH:mm:ss) \t operator \t L \t a \t b \t dE \t standart \t r360,...,r740
import com.healthmarketscience.jackcess.*;
import java.io.*;
import java.nio.file.*;
import java.text.SimpleDateFormat;
import java.util.*;

public class MdbOlustur {
  public static void main(String[] a) throws Exception {
    File out = new File(a[0]);
    String mode = a[1];
    Database db = out.exists() ? DatabaseBuilder.open(out)
        : new DatabaseBuilder(out).setFileFormat(Database.FileFormat.V2000).create();
    Table t = db.getTable("OLCUMLER");
    if (t == null) {
      TableBuilder tb = new TableBuilder("OLCUMLER")
          .addColumn(new ColumnBuilder("OLCUM_NO", DataType.LONG))
          .addColumn(new ColumnBuilder("NUMUNE_ADI", DataType.TEXT).setLength(100))
          .addColumn(new ColumnBuilder("TARIH", DataType.SHORT_DATE_TIME))
          .addColumn(new ColumnBuilder("OPERATOR", DataType.TEXT).setLength(50))
          .addColumn(new ColumnBuilder("L_DEG", DataType.DOUBLE))
          .addColumn(new ColumnBuilder("A_DEG", DataType.DOUBLE))
          .addColumn(new ColumnBuilder("B_DEG", DataType.DOUBLE))
          .addColumn(new ColumnBuilder("DE2000", DataType.DOUBLE))
          .addColumn(new ColumnBuilder("STANDART", DataType.TEXT).setLength(100))
          .addColumn(new ColumnBuilder("ACIKLAMA", DataType.MEMO));
      if (mode.equals("genis"))
        for (int nm = 360; nm <= 740; nm += 10) tb.addColumn(new ColumnBuilder("R" + nm, DataType.DOUBLE));
      t = tb.toTable(db);
      if (mode.equals("uzun"))
        new TableBuilder("SPEKTRUM")
            .addColumn(new ColumnBuilder("OLCUM_NO", DataType.LONG))
            .addColumn(new ColumnBuilder("DALGA_BOYU", DataType.INT))
            .addColumn(new ColumnBuilder("YANSIMA", DataType.DOUBLE))
            .toTable(db);
    }
    Table sp = db.getTable("SPEKTRUM");
    SimpleDateFormat f = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss");
    BufferedReader in = new BufferedReader(new InputStreamReader(System.in, "UTF-8"));
    String line;
    while ((line = in.readLine()) != null) {
      if (line.isBlank()) continue;
      String[] p = line.split("\t", -1);
      String[] r = p[9].split(",");
      List<Object> row = new ArrayList<>(Arrays.asList(Integer.parseInt(p[0]), p[1], f.parse(p[2]), p[3],
          nz(p[4]), nz(p[5]), nz(p[6]), nz(p[7]), p[8].isEmpty() ? null : p[8], "uygulama kaydı"));
      if (sp == null && !p[9].isEmpty()) for (String v : r) row.add(Double.parseDouble(v));
      t.addRow(row.toArray());
      if (sp != null && !p[9].isEmpty()) for (int i = 0; i < r.length; i++) sp.addRow(Integer.parseInt(p[0]), 360 + 10 * i, Double.parseDouble(r[i]));
    }
    db.close();
  }
  static Double nz(String s) { return s.isEmpty() ? null : Double.parseDouble(s); }
}
