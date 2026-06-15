# گزارش فعلی پیاده سازی LRP-PS

## اصلاح مدل

در مدل فعلی، large green vehicle ها به محل تقاضاها نمی روند. نقش آن ها فقط
رساندن بسته ها از depot به تسهیلات بازشده است. بنابراین تقاضاها فقط از دو راه
برآورده می شوند:

1. تخصیص مشتری به pick-up station بازشده، در شعاع پوشش و ظرفیت آن؛
2. تحویل مستقیم توسط small green vehicle.

هزینه رفت وبرگشت large GV برای هر تسهیل بازشده در هزینه ثابت موثر تسهیل لحاظ
شده است:

`f_bar_l = f_l + phi * (d_0l + d_l0)`

صرفه جویی travel نسبت به پرداخت کامل رفت وبرگشت نیز گزارش می شود:

`large_gv_travel_saving = (1 - phi) * sum_opened_l (d_0l + d_l0)`

## روش های مقایسه شده

فقط دو روش در خروجی نهایی مقایسه می شوند:

1. `paper_branch_price`: روش مقاله بر اساس ستون های الگوی تسهیل و مسیرهای small GV.
2. `branch_cut_mci`: مدل فشرده با Branch-and-Cut و جداسازی minimal cover inequalities.

## تحلیل MCI

MCI برای هر تسهیل از محدودیت ظرفیت ساخته می شود. اگر مجموعه کمینه `C` از
مشتریان ظرفیت تسهیل `l` را نقض کند، نامساوی زیر معتبر است:

`sum_{i in C} z_il <= (|C| - 1) v_l`

این cut جواب صحیح موجه را حذف نمی کند، ولی می تواند جواب های کسری relaxation را
حذف کند. در داده فعلی، اثر MCI روی کران ریشه محدود است:

- در نمونه `cluster_corner_n12_p3` تعداد 56 cover candidate تولید شد و کران LP
  حدود 0.23 درصد نسبت به optimum بهتر شد.
- در نمونه های دیگر یا cover وجود نداشت یا coverها در جواب LP ریشه violated
  نبودند، بنابراین کران ریشه بهتر نشد.
- در Branch-and-Cut، برای نمونه خوشه ای 24 cut واقعاً در گره های fractional
  اضافه شد. برای نمونه های دیگر cut فعال نشد یا candidate وجود نداشت.

پس MCI برای این داده ها معتبر و قابل استفاده در Branch-and-Cut است، اما به تنهایی
خیلی قوی نیست. بیشترین اثر آن زمانی است که تعداد زیادی مشتری نزدیک یک تسهیل
باشند و ظرفیت تسهیل tight شود.

## خروجی ها

- `results/06_comparison/comparison_results.csv`: زمان حل و مقدار هدف دو روش.
- `results/06_comparison/mci_bound_analysis.csv`: اثر MCI روی کران LP.
- `results/06_comparison/service_split_results.csv`: مقدار تقاضای سرویس شده توسط
  تسهیلات و small GV ها، تعداد مسیرهای small GV، سقف ناوگان، و صرفه جویی large GV.
- `results/06_comparison/mci_cut_activity.png`: تعداد cover candidate و cut اضافه شده.

## اجرای فعلی

```powershell
python main.py --time-limit 60
```

فعلا ارائه PowerPoint ساخته نمی شود تا زمانی که مدل نهایی تایید شود.

